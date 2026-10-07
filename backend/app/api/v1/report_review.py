"""核对草稿、精确确认与分页历史，服务端逐报告检查本人权限。"""
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.api.v1.report_workflow import validate
from app.db.session import get_db
from app.models.patient_report import ReportReviewVersion
from app.schemas.report_review import ConfirmReview, SaveReviewDraft
from app.services import report_review as service

router = APIRouter()


async def owned(db, user, report_id, *, lock=False):
    require_patient(user)
    return await service.owned(db, user.id, report_id, lock=lock)


@router.get('/reports/{report_id}/review')
async def get_review(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await service.workspace(db, await owned(db, user, report_id))


@router.post('/reports/{report_id}/review/drafts', status_code=201)
async def save_draft(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    version = await service.save_draft(db, report, validate(SaveReviewDraft, body))
    return {'version': service.version_view(version, report, payload=True), 'workspace': await service.workspace(db, report)}


@router.post('/reports/{report_id}/review/confirm', status_code=201)
async def confirm(report_id: UUID, user: CurrentUser, body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id, lock=True)
    version = await service.confirm(db, report, validate(ConfirmReview, body))
    return {'version': service.version_view(version, report, payload=True), 'workspace': await service.workspace(db, report)}


@router.get('/reports/{report_id}/review/history')
async def history(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db),
                  page: Annotated[int, Query(ge=1, le=100000)] = 1,
                  limit: Annotated[int, Query(ge=1, le=50)] = 20):
    report = await owned(db, user, report_id)
    scoped = ReportReviewVersion.report_id == report.id
    total = await db.scalar(select(func.count()).select_from(ReportReviewVersion).where(scoped))
    versions = (await db.scalars(select(ReportReviewVersion).where(scoped).order_by(ReportReviewVersion.revision.desc())
        .offset((page-1)*limit).limit(limit))).all()
    return {'items': [service.version_view(item, report) for item in versions], 'total': total, 'page': page, 'limit': limit}


@router.get('/reports/{report_id}/review/versions/{version_id}')
async def get_version(report_id: UUID, version_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    report = await owned(db, user, report_id)
    version = await service.load_version(db, report.id, version_id, payload=True)
    result = service.version_view(version, report, payload=True)
    if version.candidate_job_id:
        from app.services.report_processing import load_job
        candidate = await load_job(db, version.candidate_job_id, report_id=report.id, payload=True)
        result['original_candidate'] = candidate.result if candidate and candidate.status == 'completed' else None
    return result
