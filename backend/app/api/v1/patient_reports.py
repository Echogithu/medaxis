"""独立归档入口：仅保存本人原件，不投递解析任务或调用模型。"""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import String, and_, case, cast, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.db.session import get_db
from app.models.patient_report import PatientReport, PatientReportFile, ReportProcessingJob, ReportUploadSubmission
from app.models.user import User
from app.schemas.patient_report import ReportEdit, ReportUpload
from app.services.report_files import MAX_FILE_BYTES, MAX_REPORT_FILES, MAX_REPORT_PAGES, ReportFileError, detect_report_type, inspect_report_file
from app.services.report_review import changed_source, summary as review_summary

router = APIRouter()
# 同一 API 进程最多两个文件验证子进程，避免图片/PDF 解码抢占整个服务。
_inspection_slots = asyncio.Semaphore(2)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe_filename(value):
    filename = re.sub(r'[\x00-\x1f\x7f]', '', (value or '').replace('\\', '/').split('/')[-1]).strip()
    if not filename or len(filename) > 255:
        raise HTTPException(422, '文件名称为空或过长，请更换名称后重试')
    return filename


def file_metadata(item):
    return {key: getattr(item, key) for key in ('id', 'position', 'filename', 'mime_type', 'byte_size', 'page_count')}


def serialize(item, files, processing=None):
    return {key: getattr(item, key) for key in ('id', 'title', 'category', 'institution', 'examination_date',
        'report_date', 'notes', 'ownership_declared', 'revision', 'source_version', 'lifecycle_revision', 'trashed_at', 'created_at', 'updated_at')} | {
        'source': 'patient_upload', 'archive_status': 'trash' if item.trashed_at else 'archived', 'extraction_status': (processing or {}).get('extract', 'not_started'),
        'ai_status': (processing or {}).get('ai', 'not_started'),
        'file_count': len(files), 'page_count': sum(file.page_count for file in files),
        'files': [file_metadata(file) for file in files]} | review_summary(item)


async def report_files(db, report_id):
    return (await db.scalars(select(PatientReportFile).where(PatientReportFile.report_id == report_id)
                            .order_by(PatientReportFile.position))).all()


async def processing_states(db, reports):
    """只批量读取任务元数据；列表不取原始文字、预览或模型结果。"""
    grouped = {item.id: {} for item in reports}
    indexed = {item.id: item for item in reports}
    if not reports:
        return grouped
    jobs = (await db.scalars(select(ReportProcessingJob).join(PatientReport, PatientReport.id == ReportProcessingJob.report_id)
        .where(ReportProcessingJob.report_id.in_(indexed), or_(
            and_(ReportProcessingJob.kind == 'extract', PatientReport.workflow['extract_id'].astext == cast(ReportProcessingJob.id, String)),
            and_(ReportProcessingJob.kind == 'ai', PatientReport.workflow['ai_id'].astext == cast(ReportProcessingJob.id, String))))
        .order_by(ReportProcessingJob.created_at.desc(), ReportProcessingJob.id.desc()))).all()
    for job in jobs:
        item = indexed[job.report_id]
        expected = digest([item.source_version, item.content_hash, item.category if job.kind == 'ai' else None])
        if job.source_hash == expected and job.kind not in grouped[item.id]:
            grouped[item.id][job.kind] = job.status
    return grouped


async def owned_report(db, user_id, report_id, *, lock=False):
    statement = select(PatientReport).where(PatientReport.id == report_id, PatientReport.patient_id == user_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    item = await db.scalar(statement)
    if item is None:
        raise HTTPException(404, '报告不存在或无法访问')
    if item.trashed_at is not None:
        raise HTTPException(410, '报告已移入回收站，请先恢复后再查看或处理')
    return item


async def replay(db, patient_id, data, fingerprint):
    receipt = await db.get(ReportUploadSubmission, (patient_id, data.request_id))
    if receipt is not None:
        if receipt.request_fingerprint != fingerprint:
            raise HTTPException(409, '该提交编号已用于不同内容，请重新提交')
        if receipt.report_id is None:
            raise HTTPException(410, '该提交对应的报告已彻底删除，原提交不会重新创建；如需重新归档请发起新提交')
        item = await owned_report(db, patient_id, receipt.report_id)
        states = await processing_states(db, [item])
        return serialize(item, await report_files(db, item.id), states[item.id]) | {'upload_outcome': receipt.outcome}
    item = await db.scalar(select(PatientReport).where(PatientReport.patient_id == patient_id, PatientReport.request_id == data.request_id))
    if item is not None:
        if item.request_fingerprint != fingerprint:
            raise HTTPException(409, '该提交编号已用于不同内容，请重新提交')
        if item.trashed_at is not None:
            raise HTTPException(410, '报告已移入回收站，原提交不会重新归档；请先恢复报告')
        states = await processing_states(db, [item])
        return serialize(item, await report_files(db, item.id), states[item.id]) | {'upload_outcome': 'archived'}
    return None


@router.post('/reports', status_code=201)
async def upload_report(user: CurrentUser, metadata: Annotated[str, Form(max_length=16000)],
                        files: Annotated[list[UploadFile], File()], db: AsyncSession = Depends(get_db)):
    require_patient(user)
    try:
        data = ReportUpload.model_validate_json(metadata)
    except ValidationError:
        # 不把原始报告信息或 Pydantic input 内容回显到错误日志和响应。
        raise HTTPException(422, '报告信息无效，请核对名称、类别、日期和本人归属确认') from None
    if not 1 <= len(files) <= MAX_REPORT_FILES:
        raise HTTPException(422, f'每份报告需有1至{MAX_REPORT_FILES}个文件')
    prepared = []
    for position, file in enumerate(files):
        content = await file.read(MAX_FILE_BYTES + 1)
        filename = safe_filename(file.filename)
        try:
            mime = detect_report_type(content, filename, file.content_type)
        except ReportFileError as error:
            raise HTTPException(422, {'code': error.code, 'message': error.message, 'file_position': position}) from None
        prepared.append({'filename': filename, 'mime_type': mime, 'content': content,
                         'sha256': hashlib.sha256(content).hexdigest()})
    # 默认ask/null不改变旧上传合同的hash，旧创建编号仍可重放。
    fingerprint_fields = data.model_dump(mode='json', exclude={'request_id', 'duplicate_mode', 'duplicate_report_id'})
    if data.duplicate_mode != 'ask':
        fingerprint_fields.update(duplicate_mode=data.duplicate_mode, duplicate_report_id=str(data.duplicate_report_id) if data.duplicate_report_id else None)
    fingerprint = digest({'metadata': fingerprint_fields,
                          'files': [{key: file[key] for key in ('filename', 'mime_type', 'sha256')} for file in prepared]})
    existing = await replay(db, user.id, data, fingerprint)
    if existing is not None:
        return existing
    page_count = 0
    for position, file in enumerate(prepared):
        try:
            async with _inspection_slots:
                inspected = await inspect_report_file(file['content'], file['filename'], file['mime_type'])
        except ReportFileError as error:
            raise HTTPException(422, {'code': error.code, 'message': error.message, 'file_position': position}) from None
        file['page_count'] = inspected['page_count']
        page_count += inspected['page_count']
        if page_count > MAX_REPORT_PAGES:
            raise HTTPException(422, f'同一份报告合计不得超过{MAX_REPORT_PAGES}页')
    # 验证结束才取得短锁；并发同一患者提交由 DB 唯一约束和锁一起保证幂等。
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = await replay(db, user.id, data, fingerprint)
    if existing is not None:
        return existing
    content_hash = digest([file['sha256'] for file in prepared])
    if data.duplicate_mode == 'reuse':
        item = await owned_report(db, user.id, data.duplicate_report_id, lock=True)
        if item.content_hash != content_hash:
            raise HTTPException(409, '选定报告与本次原件不同，请重新检查重复报告或选择另存')
        db.add(ReportUploadSubmission(patient_id=user.id, request_id=data.request_id,
            request_fingerprint=fingerprint, report_id=item.id, outcome='reused'))
        states = await processing_states(db, [item])
        response = serialize(item, await report_files(db, item.id), states[item.id]) | {'upload_outcome': 'reused'}
        await db.commit()
        return response
    if data.duplicate_mode == 'ask':
        matches = (await db.scalars(select(PatientReport).where(PatientReport.patient_id == user.id,
            PatientReport.trashed_at.is_(None), PatientReport.content_hash == content_hash).order_by(PatientReport.created_at.desc(), PatientReport.id.desc()).limit(6))).all()
        if matches:
            raise HTTPException(409, jsonable_encoder({'code': 'duplicate_report', 'message': '相同原件已归档，请选择复用已有报告或另存一份',
                'more': len(matches) > 5, 'reports': [{key: getattr(item, key) for key in (
                    'id', 'title', 'category', 'institution', 'examination_date', 'report_date', 'created_at')} for item in matches[:5]]}))
    item = PatientReport(patient_id=user.id, request_id=data.request_id, request_fingerprint=fingerprint,
                         content_hash=content_hash,
                         **data.model_dump(exclude={'request_id', 'duplicate_mode', 'duplicate_report_id'}))
    db.add(item)
    await db.flush()
    originals = [PatientReportFile(report_id=item.id, position=position, byte_size=len(file['content']), **file)
                 for position, file in enumerate(prepared)]
    db.add_all(originals)
    db.add(ReportUploadSubmission(patient_id=user.id, request_id=data.request_id,
        request_fingerprint=fingerprint, report_id=item.id, outcome='archived'))
    await db.commit()
    return serialize(item, originals) | {'upload_outcome': 'archived'}


@router.get('/reports')
async def list_reports(user: CurrentUser, db: AsyncSession = Depends(get_db),
                        search: Annotated[str, Query(max_length=200)] = '',
                        category: Literal['lab', 'imaging', 'other'] | None = None,
                        pending_only: bool = False,
                        archive: Literal['active', 'trash'] = 'active',
                        page: Annotated[int, Query(ge=1, le=100000)] = 1,
                        limit: Annotated[int, Query(ge=1, le=50)] = 12):
    require_patient(user)
    ownership = PatientReport.patient_id == user.id
    filters = [ownership, PatientReport.trashed_at.is_(None) if archive == 'active' else PatientReport.trashed_at.is_not(None)]
    if category:
        filters.append(PatientReport.category == category)
    if search.strip():
        value = search.strip()
        filters.append(or_(*(column.contains(value, autoescape=True) for column in (
            PatientReport.title, PatientReport.institution, cast(PatientReport.examination_date, String), cast(PatientReport.report_date, String)))))
    state = PatientReport.review_state
    confirmed = func.coalesce(and_(state['confirmed_id'].astext.is_not(None),
        state['confirmed_epoch'].as_integer() == func.coalesce(state['epoch'].as_integer(), 0),
        state['confirmed_source_version'].as_integer() == PatientReport.source_version,
        state['confirmed_category'].astext == PatientReport.category,
        state['confirmed_content_hash'].astext == PatientReport.content_hash,
        state['confirmed_revision'].as_integer() >= func.coalesce(state['draft_revision'].as_integer(), 0)), False)
    if pending_only:
        filters.append(not_(confirmed))
    total = await db.scalar(select(func.count()).select_from(PatientReport).where(*filters))
    stats = (await db.execute(select(func.count(), func.max(PatientReport.examination_date),
        func.sum(case((confirmed, 0), else_=1))).select_from(PatientReport).where(ownership, PatientReport.trashed_at.is_(None)))).one()
    trashed = await db.scalar(select(func.count()).select_from(PatientReport).where(ownership, PatientReport.trashed_at.is_not(None)))
    items = (await db.scalars(select(PatientReport).where(*filters).order_by(PatientReport.created_at.desc(), PatientReport.id.desc())
                             .offset((page - 1) * limit).limit(limit))).all()
    originals = (await db.scalars(select(PatientReportFile).where(PatientReportFile.report_id.in_([item.id for item in items]))
                                 .order_by(PatientReportFile.position))).all() if items else []
    grouped = {item.id: [] for item in items}
    for file in originals:
        grouped[file.report_id].append(file)
    states = await processing_states(db, items)
    return {'items': [serialize(item, grouped[item.id], states[item.id]) for item in items], 'total': total, 'page': page, 'limit': limit,
            'stats': {'archived': stats[0], 'pending_review': stats[2] or 0, 'latest_examination_date': stats[1], 'trashed': trashed}}


@router.get('/reports/{report_id}')
async def get_report(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(user)
    item = await owned_report(db, user.id, report_id)
    states = await processing_states(db, [item])
    return serialize(item, await report_files(db, item.id), states[item.id])


@router.patch('/reports/{report_id}')
async def edit_report(report_id: UUID, data: ReportEdit, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(user)
    item = await owned_report(db, user.id, report_id, lock=True)
    if item.revision != data.expected_revision:
        raise HTTPException(409, '报告已在其他页面更新，本页输入仍保留，请对照最新版本')
    if item.category != data.category:
        from app.services.report_processing import invalidate_category
        await db.refresh(item, ['workflow'])
        await invalidate_category(db, item)
        changed_source(item)
    for key, value in data.model_dump(exclude={'expected_revision'}).items():
        setattr(item, key, value)
    item.revision += 1
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    states = await processing_states(db, [item])
    return serialize(item, await report_files(db, item.id), states[item.id])


@router.get('/reports/{report_id}/files/{file_id}')
async def original_file(report_id: UUID, file_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(user)
    await owned_report(db, user.id, report_id)
    row = (await db.execute(select(PatientReportFile.filename, PatientReportFile.mime_type, PatientReportFile.content)
                           .where(PatientReportFile.id == file_id, PatientReportFile.report_id == report_id))).one_or_none()
    if row is None:
        raise HTTPException(404, '原件不存在或无法访问')
    return Response(content=row.content, media_type=row.mime_type, headers={
        'Content-Disposition': f"attachment; filename*=UTF-8''{quote(row.filename, safe='')}",
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


from app.api.v1.report_workflow import router as workflow_router
router.include_router(workflow_router)
from app.api.v1.report_review import router as review_router
router.include_router(review_router)
from app.api.v1.report_links import router as links_router
router.include_router(links_router)
from app.api.v1.report_lifecycle import router as lifecycle_router
router.include_router(lifecycle_router)
