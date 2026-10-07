"""仅患者侧引用，不复制临床内容或扩大任何医生/模型权限。"""
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select

from app.models.medical_case import MedicalCase
from app.models.patient_report import ReportCaseLink, ReportManagementOperation, ReportReviewVersion
from app.services.report_candidates import fingerprint
from app.services.report_review import now, source_hash, summary


def current_pin(report):
    value = (report.review_state or {}).get('confirmed_id')
    return UUID(value) if value and summary(report)['review_status'] == 'patient_confirmed' else None


def link_status(link, report):
    if link.source_hash != source_hash(report):
        return 'source_changed'
    if link.review_version_id != current_pin(report):
        return 'review_changed'
    return 'patient_confirmed' if link.review_version_id else 'unverified'


def link_view(link, report, case_id, title, status, review_revision=None):
    return {'case_id': case_id, 'title': title, 'case_status': status,
        'source_version': link.source_version, 'review_version_id': link.review_version_id,
        'review_revision': review_revision, 'status': link_status(link, report),
        'created_at': link.created_at, 'updated_at': link.updated_at}


async def workspace(db, report):
    # 只取病例标题与版本元数据，避免ORM自动载入病例会话/资料及核对正文。
    rows = (await db.execute(select(ReportCaseLink, MedicalCase.id, MedicalCase.title, MedicalCase.status,
        ReportReviewVersion.revision).join(MedicalCase, MedicalCase.id == ReportCaseLink.case_id)
        .outerjoin(ReportReviewVersion, ReportReviewVersion.id == ReportCaseLink.review_version_id)
        .where(ReportCaseLink.report_id == report.id, MedicalCase.patient_id == report.patient_id)
        .order_by(ReportCaseLink.created_at, ReportCaseLink.case_id))).all()
    return {'links_revision': report.links_revision, 'review_revision': (report.review_state or {}).get('revision', 0),
        'source_epoch': (report.review_state or {}).get('epoch', 0),
        'source_hash': source_hash(report), 'source_version': report.source_version,
        'current_review_version_id': current_pin(report),
        'items': [link_view(link, report, case_id, title, status, revision)
                  for link, case_id, title, status, revision in rows]}


async def save(db, report, data):
    contract = fingerprint(['case_links', data.model_dump(mode='json')])
    existing = await db.scalar(select(ReportManagementOperation).where(
        ReportManagementOperation.report_id == report.id, ReportManagementOperation.request_id == data.request_id))
    if existing:
        if existing.kind != 'case_links' or existing.request_fingerprint != contract:
            raise HTTPException(409, '该提交编号已用于不同关联内容，请重新提交')
        return existing
    if (report.links_revision != data.expected_links_revision or source_hash(report) != data.expected_source_hash
        or (report.review_state or {}).get('revision', 0) != data.expected_review_revision):
        raise HTTPException(409, '关联或报告来源已在其他页面更新，请刷新对照后重新选择')
    # 与病例删除互斥；全组先校验再变更，单个他人ID不能留下部分成功。
    owned_ids = (await db.scalars(select(MedicalCase.id).where(MedicalCase.id.in_(data.case_ids),
        MedicalCase.patient_id == report.patient_id).order_by(MedicalCase.id).with_for_update())).all() if data.case_ids else []
    if set(owned_ids) != set(data.case_ids):
        raise HTTPException(404, '所选病例不存在或无法访问，请刷新病例列表')
    rows = (await db.scalars(select(ReportCaseLink).where(ReportCaseLink.report_id == report.id))).all()
    indexed = {row.case_id: row for row in rows}
    for row in rows:
        if row.case_id not in data.case_ids:
            await db.delete(row)
    for case_id in data.case_ids:
        row = indexed.get(case_id)
        if row is None:
            row = ReportCaseLink(report_id=report.id, case_id=case_id)
            db.add(row)
        if case_id not in indexed or case_id in data.refresh_case_ids:
            row.source_version, row.source_hash, row.review_version_id = report.source_version, source_hash(report), current_pin(report)
            row.updated_at = now()
    report.links_revision += 1
    report.updated_at = now()
    operation = ReportManagementOperation(report_id=report.id, request_id=data.request_id,
        request_fingerprint=contract, kind='case_links', revision=report.links_revision)
    db.add(operation)
    await db.flush()
    return operation
