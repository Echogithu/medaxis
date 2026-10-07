"""独立报告的可恢复管理；与患者治疗安排没有写入关系。"""
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from app.models.patient_report import ReportCaseLink, ReportLifecycleSubmission, ReportProcessingJob
from app.models.user import User
from app.services import report_processing as processing
from app.services.report_candidates import fingerprint
from app.services.report_review import source_hash


async def workspace(db, report):
    from app.api.v1.patient_reports import report_files, serialize
    pending = (await db.execute(select(ReportProcessingJob.id, ReportProcessingJob.status, ReportProcessingJob.dispatch_started_at)
        .where(ReportProcessingJob.report_id == report.id, ReportProcessingJob.status.in_(['queued', 'processing']))
        .order_by(ReportProcessingJob.id))).all()
    links = await db.scalar(select(func.count()).select_from(ReportCaseLink).where(ReportCaseLink.report_id == report.id))
    dispatched = bool(await db.scalar(select(ReportProcessingJob.id).where(ReportProcessingJob.report_id == report.id,
        ReportProcessingJob.dispatch_started_at.is_not(None)).limit(1)))
    token = fingerprint([report.lifecycle_revision, report.revision, report.links_revision,
        (report.review_state or {}).get('revision', 0), source_hash(report),
        (report.workflow or {}).get('revision', 0), report.trashed_at.isoformat() if report.trashed_at else None,
        [(str(row.id), row.status, row.dispatch_started_at.isoformat() if row.dispatch_started_at else None) for row in pending], links, dispatched])
    return {'report': serialize(report, await report_files(db, report.id)), 'state_token': token,
        'links_count': links, 'pending_jobs': len(pending), 'has_dispatched_text': dispatched}


async def receipt(db, patient_id, request_id, contract):
    operation = await db.get(ReportLifecycleSubmission, (patient_id, request_id))
    if operation is not None and operation.request_fingerprint != contract:
        raise HTTPException(409, '该管理编号已用于不同操作，请重新确认')
    return operation


async def response(db, operation, report):
    return {'operation': {'request_id': operation.request_id, 'kind': operation.kind, 'revision': operation.revision},
        'deleted': report is None, 'workspace': await workspace(db, report) if report is not None else None}


async def cancel_all(db, report):
    # 与worker一致先锁报告，再按任务ID加锁；清除租约使晚到结果无法发布。
    jobs = (await db.scalars(select(ReportProcessingJob).where(ReportProcessingJob.report_id == report.id,
        ReportProcessingJob.status.in_(['queued', 'processing'])).order_by(ReportProcessingJob.id).with_for_update())).all()
    for job in jobs:
        job.status, job.lease = 'cancelled', None
        job.completed_at = job.updated_at = processing.now()
        job.error_code, job.error_message = 'report_removed', '报告已移除，任务不会继续发布结果'
    processing.update_state(report, extract_id=None, ai_id=None, preview=None)


async def perform(db, patient_id, report_id, kind, data):
    # 与上传统一为patient→report→job，跨报告复用同一管理UUID也只能消费一次。
    await db.execute(select(User.id).where(User.id == patient_id).with_for_update())
    contract = fingerprint([str(report_id), kind, data.model_dump(mode='json')])
    previous = await receipt(db, patient_id, data.request_id, contract)
    report = await processing.workspace_report(db, report_id, patient_id, lock=True, include_trashed=True)
    # 等待并发purge的报告锁后再次查receipt；没有报告也可证明同一删除已经完成。
    previous = previous or await receipt(db, patient_id, data.request_id, contract)
    if previous is not None:
        return await response(db, previous, report)
    if report is None:
        raise HTTPException(404, '报告不存在或无法访问')
    current = await workspace(db, report)
    if current['state_token'] != data.expected_state_token:
        raise HTTPException(409, '报告或整理进度已更新，请重新查看影响并确认；尚未执行本次操作')
    if kind == 'trash' and report.trashed_at is not None:
        raise HTTPException(409, '报告已在回收站，请刷新状态')
    if kind != 'trash' and report.trashed_at is None:
        raise HTTPException(409, '请先将报告移入回收站，再执行恢复或彻底删除')
    report.lifecycle_revision += 1
    operation = ReportLifecycleSubmission(patient_id=patient_id, request_id=data.request_id,
        target_id=report_id, request_fingerprint=contract, kind=kind, revision=report.lifecycle_revision)
    db.add(operation)
    if kind == 'purge':
        # 原件/文字/核对/任务/引用由FK级联删除，上传receipt保留SET NULL墓碑。
        await db.delete(report)
        await db.flush()
        return await response(db, operation, None)
    await cancel_all(db, report)
    await db.execute(delete(ReportCaseLink).where(ReportCaseLink.report_id == report.id))
    report.links_revision += 1
    report.trashed_at = processing.now() if kind == 'trash' else None
    report.updated_at = processing.now()
    await db.flush()
    return await response(db, operation, report)
