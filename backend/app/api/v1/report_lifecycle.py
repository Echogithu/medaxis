"""本人回收站操作，永久删除确认与提交重放。"""
from typing import Any, Literal
from uuid import UUID
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.api.v1.report_workflow import validate
from app.db.session import get_db
from app.schemas.report_lifecycle import ReportLifecycleRequest, ReportPurgeRequest
from app.services import report_lifecycle as service
from app.services.report_processing import workspace_report

router = APIRouter()


@router.get('/reports/{report_id}/lifecycle')
async def management(report_id: UUID, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(user)
    report = await workspace_report(db, report_id, user.id, include_trashed=True)
    if report is None:
        raise HTTPException(404, '报告不存在或无法访问')
    return await service.workspace(db, report)


@router.post('/reports/{report_id}/lifecycle/{action}')
async def change(report_id: UUID, action: Literal['trash', 'restore', 'purge'], user: CurrentUser,
                 body: Any = Body(...), db: AsyncSession = Depends(get_db)):
    require_patient(user)
    data = validate(ReportPurgeRequest if action == 'purge' else ReportLifecycleRequest, body)
    result = await service.perform(db, user.id, report_id, action, data)
    await db.commit()
    return result
