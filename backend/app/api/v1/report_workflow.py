"""患者本人报告工作区：本地识字与脱敏文本的逐次同意。"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.db.session import get_db
from app.schemas.patient_report import ReportAIRequest, ReportExtractRequest, ReportPreviewRequest
from app.services import report_processing as service

router = APIRouter()


def validate(schema, data):
    try:
        return schema.model_validate(data)
    except ValidationError:
        raise HTTPException(422, '提交内容无效，请核对页数、文字、版本和逐次确认') from None


async def owned(db, user, report_id, *, lock=False):
    require_patient(user)
    report = await service.workspace_report(db, report_id, user.id, lock=lock)
    if report is None:
        raise HTTPException(404, '报告不存在或无法访问')
    return report


@router.get('/reports/{report_id}/workspace')
async def get_workspace(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await service.workspace(db, await owned(db, user, report_id))


@router.post('/reports/{report_id}/extract', status_code=202)
async def start_extract(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    job = await service.create_extract(db, report, validate(ReportExtractRequest, body))
    return {'job': service.job_view(job), 'workspace': await service.workspace(db, report)}


@router.post('/reports/{report_id}/preview')
async def prepare_preview(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    preview = await service.create_preview(db, report, user, validate(ReportPreviewRequest, body))
    return {'preview': preview, 'workspace': await service.workspace(db, report)}


@router.post('/reports/{report_id}/ai', status_code=202)
async def start_ai(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    job = await service.create_ai(db, report, user, validate(ReportAIRequest, body))
    return {'job': service.job_view(job), 'workspace': await service.workspace(db, report)}


@router.post('/reports/{report_id}/jobs/{job_id}/cancel')
async def cancel_job(report_id: UUID, job_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    job = await service.load_job(db, job_id, lock=True, report_id=report.id)
    if job is None or job.report_id != report.id:
        raise HTTPException(404, '整理任务不存在或无法访问')
    if job.status in ('queued', 'processing'):
        job.status, job.completed_at, job.updated_at = 'cancelled', service.now(), service.now()
        service.update_state(report)
    await db.commit()
    return {'job': service.job_view(job), 'workspace': await service.workspace(db, report),
        'message': ('已停止发布本次结果；已经或可能发送的文字无法召回' if job.dispatch_started_at
            else '任务已停止，不会发送本次待处理文字') if job.status == 'cancelled' else '任务已经结束，可查看保存的进度和结果'}
