"""本人核对版本独立于AI任务；所有写入只追加，不更改既有正文。"""
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app.models.patient_report import PatientReport, PatientReportFile, ReportProcessingJob, ReportReviewVersion
from app.services.report_candidates import fingerprint


def now():
    return datetime.now(timezone.utc)


def source_hash(report):
    return fingerprint([report.source_version, report.content_hash, report.category, (report.review_state or {}).get('epoch', 0)])


def changed_source(report, pages=None):
    """代次单调递增，改回旧类别/文字不能复活旧确认。接收模型变化不改变人工核对来源。"""
    state = deepcopy(report.review_state or {})
    text_hash = fingerprint(pages) if pages is not None else None
    if pages is not None and state.get('text_hash') == text_hash:
        return
    state['epoch'] = state.get('epoch', 0) + 1
    if pages is not None:
        state['text_hash'] = text_hash
    report.review_state = state


def summary(report):
    state = report.review_state or {}
    if state.get('confirmed_id') and state.get('confirmed_source_hash') != source_hash(report):
        status = 'source_changed'
    elif state.get('draft_id') and state.get('draft_revision', 0) > state.get('confirmed_revision', 0):
        status = 'draft'
    elif state.get('confirmed_id'):
        status = 'patient_confirmed'
    else:
        status = 'unverified'
    return {'review_status': status, 'review_revision': state.get('revision', 0),
        'confirmed_at': state.get('confirmed_at'), 'confirmed_revision': state.get('confirmed_revision')}


async def owned(db, patient_id, report_id, *, lock=False):
    statement = select(PatientReport).options(undefer(PatientReport.workflow)).where(
        PatientReport.id == report_id, PatientReport.patient_id == patient_id, PatientReport.trashed_at.is_(None))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    report = await db.scalar(statement)
    if report is None:
        raise HTTPException(404, '报告不存在或无法访问')
    return report


async def load_version(db, report_id, version_id, *, payload=False):
    if not version_id:
        return None
    statement = select(ReportReviewVersion).where(ReportReviewVersion.report_id == report_id,
        ReportReviewVersion.id == version_id)
    if payload:
        statement = statement.options(undefer(ReportReviewVersion.payload))
    version = await db.scalar(statement)
    if version is None:
        raise HTTPException(404, '核对版本不存在或无法访问')
    return version


def version_view(version, report, *, payload=False):
    if not version:
        return None
    result = {key: getattr(version, key) for key in ('id', 'request_id', 'revision', 'kind', 'category',
        'source_version', 'source_epoch', 'based_on_version_id', 'candidate_job_id', 'confirmed_draft_id', 'created_at')}
    result['source_current'] = version.source_hash == source_hash(report)
    if payload:
        result['content'] = deepcopy(version.payload)
    return result


async def current_candidate(db, report):
    state = report.workflow or {}
    preview = state.get('preview')
    if not preview or not state.get('ai_id'):
        return None
    job = await db.scalar(select(ReportProcessingJob).options(undefer(ReportProcessingJob.result)).where(
        ReportProcessingJob.id == state['ai_id'], ReportProcessingJob.report_id == report.id,
        ReportProcessingJob.kind == 'ai', ReportProcessingJob.status == 'completed'))
    expected = fingerprint([report.source_version, report.content_hash, report.category])
    if not job or job.source_hash != expected or job.result.get('preview_hash') != preview['hash']:
        return None
    return {'job_id': job.id, 'content': {key: deepcopy(job.result.get(key, [])) for key in ('indicators', 'sections')}}


async def workspace(db, report):
    state = report.review_state or {}
    draft = await load_version(db, report.id, state.get('draft_id'), payload=True)
    confirmed = await load_version(db, report.id, state.get('confirmed_id'), payload=True)
    return summary(report) | {'revision': state.get('revision', 0), 'source_epoch': state.get('epoch', 0),
        'source_version': report.source_version, 'source_hash': source_hash(report), 'category': report.category,
        'draft': version_view(draft, report, payload=True), 'confirmed': version_view(confirmed, report, payload=True),
        'candidate': await current_candidate(db, report)}


def expect_version(report, data):
    state = report.review_state or {}
    if (state.get('revision', 0) != data.expected_revision or state.get('epoch', 0) != data.expected_source_epoch
        or report.source_version != data.expected_source_version or source_hash(report) != data.expected_source_hash):
        raise HTTPException(409, '核对内容或来源已在其他页面更新，本页填写仍保留，请对照最新版本')


async def replay(db, report, data, kind):
    version = await db.scalar(select(ReportReviewVersion).options(undefer(ReportReviewVersion.payload)).where(
        ReportReviewVersion.report_id == report.id, ReportReviewVersion.request_id == data.request_id))
    if version:
        if version.request_fingerprint != fingerprint([kind, data.model_dump(mode='json')]):
            raise HTTPException(409, '该提交编号已用于不同核对内容，请重新提交')
        await db.commit()
    return version


async def append_version(db, report, data, kind, content, *, base=None, candidate_id=None, draft_id=None):
    state = deepcopy(report.review_state or {})
    revision = state.get('revision', 0) + 1
    version = ReportReviewVersion(report_id=report.id, request_id=data.request_id,
        request_fingerprint=fingerprint([kind, data.model_dump(mode='json')]), revision=revision, kind=kind,
        category=report.category, source_version=report.source_version, source_epoch=state.get('epoch', 0),
        source_hash=source_hash(report), payload=deepcopy(content), based_on_version_id=base.id if base else None,
        candidate_job_id=candidate_id, confirmed_draft_id=draft_id)
    db.add(version); await db.flush()
    state['revision'] = revision
    if kind == 'draft':
        state.update(draft_id=str(version.id), draft_revision=revision)
    else:
        state.update(confirmed_id=str(version.id), confirmed_revision=revision,
            confirmed_source_hash=version.source_hash, confirmed_epoch=version.source_epoch,
            confirmed_source_version=report.source_version, confirmed_category=report.category,
            confirmed_content_hash=report.content_hash, confirmed_at=version.created_at.isoformat())
    report.review_state, report.updated_at = state, now()
    await db.commit()
    return version


async def save_draft(db, report, data):
    existing = await replay(db, report, data, 'draft')
    if existing:
        return existing
    expect_version(report, data)
    content = data.content.model_dump(mode='json')
    if report.category != 'lab' and content['indicators']:
        raise HTTPException(422, '影像及其他报告请填写书面所见或结论，不填写检验指标')
    page_count = await db.scalar(select(func.sum(PatientReportFile.page_count)).where(PatientReportFile.report_id == report.id))
    if any(item['source_page'] and item['source_page'] > page_count for item in [*content['indicators'], *content['sections']]):
        raise HTTPException(422, '来源页超出原件页数；无法定位时请留空')
    base = await load_version(db, report.id, data.based_on_version_id)
    if base and base.category != report.category:
        raise HTTPException(409, '历史版本类别已变化，请按当前报告重新填写')
    candidate_id = base.candidate_job_id if base else None
    if data.candidate_job_id:
        candidate = await current_candidate(db, report)
        if not candidate or candidate['job_id'] != data.candidate_job_id:
            raise HTTPException(409, 'AI候选已经更新，请对照最新候选或人工填写')
        candidate_id = data.candidate_job_id
    return await append_version(db, report, data, 'draft', content, base=base, candidate_id=candidate_id)


async def confirm(db, report, data):
    existing = await replay(db, report, data, 'confirmed')
    if existing:
        return existing
    expect_version(report, data)
    draft = await load_version(db, report.id, data.draft_id, payload=True)
    state = report.review_state or {}
    if (draft.kind != 'draft' or str(draft.id) != state.get('draft_id') or draft.revision != state.get('revision', 0)
        or draft.source_hash != source_hash(report)):
        raise HTTPException(409, '请先保存当前来源下的最新草稿，再单独确认已对照原件')
    items, sections = draft.payload['indicators'], draft.payload['sections']
    if not items and not sections:
        raise HTTPException(422, '请先填写并保存至少一项指标或报告文字')
    if any(not item['name'].strip() or not item['raw_value'].strip() for item in items) or any(not item['text'].strip() for item in sections):
        raise HTTPException(422, '草稿还有未填写的项目或结果，请补全或移除后再确认')
    return await append_version(db, report, data, 'confirmed', draft.payload,
        base=draft, candidate_id=draft.candidate_job_id, draft_id=draft.id)
