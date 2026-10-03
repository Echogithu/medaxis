"""本人诊后记录的脱敏预览、AI整理与逐项确认。"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.care_plans import require_patient
from app.db.session import get_db
from app.models.medical_case import MedicalCase
from app.models.post_visit_feedback import PatientPostVisitFeedback
from app.schemas.post_visit_actions import GenerateActions, ConfirmActions, DismissActions
from app.services import post_visit_actions as service
from app.services.llm import LLMConfigurationError

router = APIRouter()


@router.get("/ai-actions/pending")
async def pending(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    require_patient(current_user)
    rows = (await db.execute(select(MedicalCase.id, PatientPostVisitFeedback.revision)
        .join(PatientPostVisitFeedback, PatientPostVisitFeedback.case_id == MedicalCase.id)
        .where(MedicalCase.patient_id == current_user.id,
               PatientPostVisitFeedback.payload["ai_actions"]["state"].astext == "ready")
        .order_by(PatientPostVisitFeedback.updated_at.desc()).limit(50))).all()
    return {"items": [{"case_id": str(row.id), "revision": row.revision} for row in rows]}


@router.get("/cases/{case_id}/ai-actions/preview")
async def preview(case_id: UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    try:
        view, _ = await service.preview(db, case_id, current_user)
        return view
    except LLMConfigurationError:
        raise HTTPException(503, "当前模型未配置，请稍后使用或手动登记安排") from None


@router.get("/cases/{case_id}/ai-actions")
async def get(case_id: UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    _, row = await service.feedback_source(db, case_id, current_user)
    return service.result(row)


@router.post("/cases/{case_id}/ai-actions/generate")
async def generate(case_id: UUID, data: GenerateActions, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    try:
        return await service.generate(db, case_id, current_user, data)
    except LLMConfigurationError:
        raise HTTPException(503, "当前模型未配置，请重新预览或手动登记安排") from None


@router.post("/cases/{case_id}/ai-actions/confirm")
async def confirm(case_id: UUID, data: ConfirmActions, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await service.confirm(db, case_id, current_user, data)


@router.post("/cases/{case_id}/ai-actions/dismiss")
async def dismiss(case_id: UUID, data: DismissActions, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await service.dismiss(db, case_id, current_user, data.draft_id)
