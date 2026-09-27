"""Patient-side API endpoints.

Phase 2a: Health profile, care plans, reminders, and health check-ins.
"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.agent import AgentSession, CarePlan, MonitoringEvent, PatientHealthProfile
from app.models.case_preparation import CasePreparationPackage
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import MedicalCase
from app.models.post_visit_feedback import PatientPostVisitFeedback
from app.models.user import User, UserRole
from app.services.case_preparation import (
    build_package,
    build_source_snapshot,
    canonical_fingerprint,
    source_fact_fingerprint,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


class PostVisitFeedbackRequest(BaseModel):
    self_reported_visit_at: AwareDatetime | None = None
    actual_department: str | None = Field(default=None, max_length=160)
    patient_summary: str | None = Field(default=None, max_length=4000)
    follow_up_items: list[str] = Field(default_factory=list, max_length=20)
    material_file_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("actual_department", "patient_summary")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("follow_up_items")
    @classmethod
    def strip_follow_up_items(cls, items: list[str]) -> list[str]:
        cleaned = [item.strip() for item in items if item.strip()]
        if any(len(item) > 500 for item in cleaned):
            raise ValueError("Each follow-up item must be at most 500 characters")
        return cleaned

    @field_validator("material_file_ids")
    @classmethod
    def unique_material_ids(cls, file_ids: list[str]) -> list[str]:
        if len(set(file_ids)) != len(file_ids):
            raise ValueError("Duplicate material file IDs are not allowed")
        return file_ids

    @model_validator(mode="after")
    def require_feedback_content(self):
        if not any((
            self.self_reported_visit_at,
            self.actual_department,
            self.patient_summary,
            self.follow_up_items,
            self.material_file_ids,
        )):
            raise ValueError("At least one post-visit field is required")
        return self


class PostVisitFeedbackUpdate(PostVisitFeedbackRequest):
    expected_revision: int = Field(ge=1)


VALID_CHRONIC_DISEASES = {
    "E11": "2型糖尿病", "I10": "原发性高血压", "I25": "冠心病",
    "I50": "慢性心力衰竭", "I48": "心房颤动", "I63": "脑梗死",
    "E78": "高脂血症", "J44": "慢阻肺", "J45": "支气管哮喘",
    "N18": "慢性肾病", "K76.0": "脂肪肝", "B18.1": "慢性乙型肝炎",
    "E05": "甲亢", "E03": "甲减", "M81": "骨质疏松",
    "M06": "类风湿关节炎", "M17": "膝骨关节炎",
    "G20": "帕金森病", "F32": "抑郁症", "F41": "焦虑障碍",
}


# ═══════════════════════════════════════════════════════════════
# Health Profile
# ═══════════════════════════════════════════════════════════════

@router.get("/profile")
async def get_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get patient health profile (flat format, matches frontend PatientProfile)."""
    result = await db.execute(
        select(PatientHealthProfile).where(
            PatientHealthProfile.patient_id == current_user.id
        )
    )
    profile = result.scalar_one_or_none()
    return {
        "id": str(current_user.id),
        "name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "date_of_birth": getattr(current_user, 'date_of_birth', None),
        "gender": current_user.gender,
        "height": profile.height if profile else None,
        "weight": profile.weight if profile else None,
        "allergies": profile.allergies if profile else [],
        "chronic_diseases": profile.chronic_diseases if profile else [],
        "medications": profile.current_medications if profile else [],
    }


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, pattern=r'^(male|female|男|女)$')
    height: int | None = Field(None, ge=50, le=300)
    weight: int | None = Field(None, ge=10, le=500)
    allergies: list[str] | None = None
    chronic_diseases: list[dict] | None = None
    medications: list[dict] | None = None


@router.patch("/profile")
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update patient profile (flat format)."""
    if data.name is not None:
        current_user.full_name = data.name
    if data.phone is not None:
        current_user.phone = data.phone
    if data.gender is not None:
        current_user.gender = data.gender

    profile = await db.scalar(
        select(PatientHealthProfile).where(
            PatientHealthProfile.patient_id == current_user.id
        )
    )
    if not profile:
        profile = PatientHealthProfile(patient_id=current_user.id)
        db.add(profile)

    if data.height is not None:
        profile.height = data.height
    if data.weight is not None:
        profile.weight = data.weight
    if data.allergies is not None:
        profile.allergies = data.allergies
    if data.chronic_diseases is not None:
        profile.chronic_diseases = data.chronic_diseases
    if data.medications is not None:
        profile.current_medications = data.medications
    profile.last_updated = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(current_user)
    await db.refresh(profile)
    return {
        "id": str(current_user.id),
        "name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "gender": current_user.gender,
        "height": profile.height,
        "weight": profile.weight,
        "allergies": profile.allergies or [],
        "chronic_diseases": profile.chronic_diseases or [],
        "medications": profile.current_medications or [],
    }


# ═══════════════════════════════════════════════════════════════
# Medical Cases
# ═══════════════════════════════════════════════════════════════

@router.get("/cases")
async def list_cases(
    current_user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's medical cases."""
    stmt = (
        select(MedicalCase)
        .where(MedicalCase.patient_id == current_user.id)
        .order_by(MedicalCase.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "chief_complaint": c.chief_complaint,
            "description": c.description,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "diagnosis": getattr(c, "diagnosis", None),
        }
        for c in result.scalars().all()
    ]


@router.get("/cases/{case_id}/recovery")
async def get_case_recovery(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """恢复患者本人病例的结构化报告、解析状态和材料元数据。"""
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=404, detail="Case not found")
    case_result = await db.execute(
        select(MedicalCase).where(
            MedicalCase.id == case_id,
            MedicalCase.patient_id == current_user.id,
        )
    )
    case = case_result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    source_session = (
        await db.get(AgentSession, case.source_session_id)
        if case.source_session_id is not None
        else None
    )
    if source_session is not None and source_session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    frontend_session_id = (source_session.context or {}).get("_frontend_sid") if source_session else None
    material_filters = [DocumentParseTask.case_id == case.id]
    if case.source_session_id is not None:
        material_filters.append(DocumentParseTask.source_session_id == case.source_session_id)
    if frontend_session_id:
        material_filters.append(DocumentParseTask.client_session_id == frontend_session_id)
    material_result = await db.execute(
        select(DocumentParseTask)
        .where(
            DocumentParseTask.owner_user_id == current_user.id,
            or_(*material_filters),
        )
        .order_by(DocumentParseTask.created_at)
    )
    materials = material_result.scalars().all()
    lab_reports = [item.result for item in materials if item.result]

    return {
        "case": {
            "id": str(case.id),
            "title": case.title,
            "chief_complaint": case.chief_complaint,
            "status": case.status.value,
            "created_at": case.created_at.isoformat() if case.created_at else None,
        },
        "report": source_session.structured_output if source_session else None,
        "lab_reports": lab_reports,
        "materials": [
            {
                "file_id": item.file_id,
                "filename": item.filename,
                "mime_type": item.mime_type,
                "status": item.status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in materials
        ],
    }


@router.get("/cases/{case_id}/materials/{file_id}")
async def download_case_material(
    case_id: uuid.UUID,
    file_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """下载患者本人病例中保存的原始材料。"""
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=404, detail="Material not found")
    case_result = await db.execute(
        select(MedicalCase).where(
            MedicalCase.id == case_id,
            MedicalCase.patient_id == current_user.id,
        )
    )
    case = case_result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Material not found")

    frontend_session_id = None
    if case.source_session_id is not None:
        source_session = await db.get(AgentSession, case.source_session_id)
        if source_session is not None and source_session.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Material not found")
        frontend_session_id = (source_session.context or {}).get("_frontend_sid") if source_session else None
    linked = [DocumentParseTask.case_id == case.id]
    if case.source_session_id is not None:
        linked.append(DocumentParseTask.source_session_id == case.source_session_id)
    if frontend_session_id:
        linked.append(DocumentParseTask.client_session_id == frontend_session_id)
    material_result = await db.execute(
        select(DocumentParseTask).where(
            DocumentParseTask.file_id == file_id,
            DocumentParseTask.owner_user_id == current_user.id,
            or_(*linked),
        )
    )
    material = material_result.scalar_one_or_none()
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")

    from urllib.parse import quote

    return Response(
        content=material.file_bytes,
        media_type=material.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(material.filename)}"},
    )


class PreparationCorrection(BaseModel):
    fact_id: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2000)

    @field_validator("value")
    @classmethod
    def strip_nonempty_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Correction value cannot be blank")
        return value


class PreparationChecklistUpdate(BaseModel):
    item_id: str = Field(min_length=1, max_length=255)
    status: str = Field(pattern=r"^(pending|ready)$")


class PreparationUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    confirmed_fact_ids: list[str] = Field(default_factory=list, max_length=100)
    patient_corrections: list[PreparationCorrection] = Field(default_factory=list, max_length=50)
    patient_questions: list[str] = Field(default_factory=list, max_length=20)
    checklist_updates: list[PreparationChecklistUpdate] = Field(default_factory=list, max_length=100)

    @field_validator("patient_questions")
    @classmethod
    def strip_questions(cls, questions: list[str]) -> list[str]:
        cleaned = [question.strip() for question in questions if question.strip()]
        if any(len(question) > 300 for question in cleaned):
            raise ValueError("Each patient question must be 300 characters or fewer")
        return cleaned


async def _load_preparation_source(
    db: AsyncSession, case_id: uuid.UUID, current_user: User, *, for_update: bool = False
) -> tuple[MedicalCase, AgentSession | None, list[DocumentParseTask], dict]:
    statement = select(MedicalCase).where(
        MedicalCase.id == case_id,
        MedicalCase.patient_id == current_user.id,
    )
    if for_update:
        statement = statement.with_for_update()
    case = await db.scalar(statement)
    if case is None or current_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=404, detail="Case not found")

    source_session = (
        await db.get(AgentSession, case.source_session_id)
        if case.source_session_id is not None
        else None
    )
    if source_session is not None and source_session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    frontend_session_id = (
        (source_session.context or {}).get("_frontend_sid") if source_session else None
    )
    material_filters = [DocumentParseTask.case_id == case.id]
    if case.source_session_id is not None:
        material_filters.append(DocumentParseTask.source_session_id == case.source_session_id)
    if frontend_session_id:
        material_filters.append(DocumentParseTask.client_session_id == frontend_session_id)
    material_result = await db.execute(
        select(DocumentParseTask)
        .where(
            DocumentParseTask.owner_user_id == current_user.id,
            or_(*material_filters),
        )
        .order_by(DocumentParseTask.file_id)
    )
    materials = list(material_result.scalars().all())
    patient_profile = await db.scalar(
        select(PatientHealthProfile).where(
            PatientHealthProfile.patient_id == current_user.id
        )
    )
    source = build_source_snapshot(case, source_session, materials, patient_profile)
    return case, source_session, materials, source


def _preparation_response(
    package_row: CasePreparationPackage,
    current_source: dict,
) -> dict:
    package = package_row.package
    current_fingerprint = canonical_fingerprint({
        "source": current_source,
        "patient_corrections": package.get("patient_corrections", []),
    })
    is_stale = (
        current_fingerprint != package_row.source_fingerprint
        or package_row.state == "needs_reassessment"
    )
    return {
        "package_id": str(package_row.id),
        "case_id": str(package_row.case_id),
        "version": package_row.version,
        "revision": package_row.revision,
        "state": "needs_reassessment" if is_stale else package_row.state,
        "is_stale": is_stale,
        "source_fingerprint": package_row.source_fingerprint,
        **package,
        "created_at": package_row.created_at.isoformat() if package_row.created_at else None,
        "updated_at": package_row.updated_at.isoformat() if package_row.updated_at else None,
    }


@router.get("/cases/{case_id}/preparation")
async def get_case_preparation(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, _, _, source = await _load_preparation_source(db, case_id, current_user)
    rows = list((await db.scalars(
        select(CasePreparationPackage)
        .where(CasePreparationPackage.case_id == case_id)
        .order_by(CasePreparationPackage.version.desc())
    )).all())
    return {
        "package": _preparation_response(rows[0], source) if rows else None,
        "history": [_preparation_response(row, source) for row in rows[1:]],
    }


@router.post("/cases/{case_id}/preparation", status_code=status.HTTP_200_OK)
async def create_case_preparation(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case, _, _, source = await _load_preparation_source(
        db, case_id, current_user, for_update=True
    )
    if not source["report"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "report_not_ready", "message": "此病例暂时没有可整理的结构化报告。"},
        )

    latest = await db.scalar(
        select(CasePreparationPackage)
        .where(CasePreparationPackage.case_id == case.id)
        .order_by(CasePreparationPackage.version.desc())
        .limit(1)
    )
    corrections = (latest.package or {}).get("patient_corrections", []) if latest else []
    corrections = [
        correction for correction in corrections
        if correction.get("source_fact_fingerprint")
        == source_fact_fingerprint(source, correction["fact_id"])
    ]
    fingerprint = canonical_fingerprint({"source": source, "patient_corrections": corrections})
    existing = await db.scalar(
        select(CasePreparationPackage).where(
            CasePreparationPackage.case_id == case.id,
            CasePreparationPackage.source_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return {"created": False, **_preparation_response(existing, source)}

    version = (latest.version if latest else 0) + 1
    package = build_package(source, corrections)
    if latest is not None:
        previous_package = latest.package or {}
        package["patient_questions"] = previous_package.get("patient_questions", [])
        previous_checklist = {
            item["id"]: item.get("status", "pending")
            for item in previous_package.get("preparation_items", [])
        }
        package["preparation_items"] = [
            {**item, "status": previous_checklist.get(item["id"], item["status"])}
            for item in package["preparation_items"]
        ]

    row = CasePreparationPackage(
        case_id=case.id,
        version=version,
        revision=1,
        source_fingerprint=fingerprint,
        source_snapshot={"source": source, "patient_corrections": corrections},
        package=package,
        state="ready_for_review",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"created": True, **_preparation_response(row, source)}


@router.patch("/cases/{case_id}/preparation/{package_id}")
async def update_case_preparation(
    case_id: uuid.UUID,
    package_id: uuid.UUID,
    data: PreparationUpdateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, _, _, source = await _load_preparation_source(
        db, case_id, current_user, for_update=True
    )
    row = await db.scalar(
        select(CasePreparationPackage)
        .where(
            CasePreparationPackage.id == package_id,
            CasePreparationPackage.case_id == case_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Preparation package not found")
    if row.revision != data.expected_revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "message": "准备包已更新，请重新载入后再保存。"},
        )

    package = dict(row.package or {})
    known_facts = package.get("known_facts", [])
    confirmable_ids = {
        fact["id"] for fact in known_facts
        if fact.get("source_type") in {"patient_reported", "patient_correction"}
        and fact.get("active", True)
    }
    unknown_ids = {fact["id"] for fact in package.get("unknown_facts", [])}
    existing_correction_ids = {
        item["fact_id"] for item in package.get("patient_corrections", [])
    }
    if any(fact_id not in confirmable_ids for fact_id in data.confirmed_fact_ids):
        raise HTTPException(status_code=422, detail="Only patient-reported facts can be confirmed")
    if any(
        correction.fact_id not in confirmable_ids | unknown_ids | existing_correction_ids
        for correction in data.patient_corrections
    ):
        raise HTTPException(status_code=422, detail="Correction must refer to a known or unknown patient fact")

    confirmed = set(data.confirmed_fact_ids)
    package["known_facts"] = [
        {**fact, "confirmed": fact["id"] in confirmed}
        if fact.get("source_type") in {"patient_reported", "patient_correction"}
        and fact.get("active", True)
        else fact
        for fact in known_facts
    ]
    corrections = {
        item["fact_id"]: item for item in package.get("patient_corrections", [])
    }
    for correction in data.patient_corrections:
        corrections[correction.fact_id] = {
            "fact_id": correction.fact_id,
            "value": correction.value.strip(),
            "source_fact_fingerprint": source_fact_fingerprint(source, correction.fact_id),
        }
    package["patient_corrections"] = list(corrections.values())
    package["patient_questions"] = data.patient_questions

    item_updates = {update.item_id: update.status for update in data.checklist_updates}
    item_ids = {item["id"] for item in package.get("preparation_items", [])}
    if not set(item_updates).issubset(item_ids):
        raise HTTPException(status_code=422, detail="Checklist item does not belong to this package")
    package["preparation_items"] = [
        {**item, "status": item_updates.get(item["id"], item.get("status", "pending"))}
        for item in package.get("preparation_items", [])
    ]
    row.package = package
    row.revision += 1
    if data.patient_corrections:
        row.state = "needs_reassessment"
    await db.commit()
    await db.refresh(row)
    return _preparation_response(row, source)


def _post_visit_feedback_response(row: PatientPostVisitFeedback) -> dict:
    payload = row.payload or {}
    return {
        "feedback_id": str(row.id),
        "case_id": str(row.case_id),
        "version": row.version,
        "revision": row.revision,
        "source_type": "patient_reported",
        "self_reported_visit_at": payload.get("self_reported_visit_at"),
        "actual_department": payload.get("actual_department"),
        "patient_summary": payload.get("patient_summary"),
        "follow_up_items": payload.get("follow_up_items", []),
        "material_file_ids": payload.get("material_file_ids", []),
        "revision_history": payload.get("revision_history", []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _load_feedback_case(
    db: AsyncSession, case_id: uuid.UUID, current_user: User, *, for_update: bool = False
) -> MedicalCase:
    statement = select(MedicalCase).where(
        MedicalCase.id == case_id,
        MedicalCase.patient_id == current_user.id,
    )
    if for_update:
        statement = statement.with_for_update()
    case = await db.scalar(statement)
    if case is None or current_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


async def _validate_feedback_materials(
    db: AsyncSession,
    case: MedicalCase,
    current_user: User,
    file_ids: list[str],
) -> None:
    if not file_ids:
        return
    material_filters = [DocumentParseTask.case_id == case.id]
    if case.source_session_id is not None:
        source_session = await db.get(AgentSession, case.source_session_id)
        if source_session is not None and source_session.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Case not found")
        material_filters.append(DocumentParseTask.source_session_id == case.source_session_id)
        frontend_session_id = (source_session.context or {}).get("_frontend_sid") if source_session else None
        if frontend_session_id:
            material_filters.append(DocumentParseTask.client_session_id == frontend_session_id)
    found = set((await db.scalars(
        select(DocumentParseTask.file_id).where(
            DocumentParseTask.file_id.in_(file_ids),
            or_(*material_filters),
            DocumentParseTask.owner_user_id == current_user.id,
            DocumentParseTask.owner_guest_id.is_(None),
        )
    )).all())
    if found != set(file_ids):
        raise HTTPException(status_code=422, detail="Material must belong to this patient and case")


@router.get("/cases/{case_id}/post-visit-feedback")
async def get_post_visit_feedback(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_feedback_case(db, case_id, current_user)
    rows = list((await db.scalars(
        select(PatientPostVisitFeedback)
        .where(PatientPostVisitFeedback.case_id == case_id)
        .order_by(PatientPostVisitFeedback.version.desc())
    )).all())
    return {
        "feedback": _post_visit_feedback_response(rows[0]) if rows else None,
        "history": [_post_visit_feedback_response(row) for row in rows[1:]],
    }


@router.post("/cases/{case_id}/post-visit-feedback", status_code=status.HTTP_200_OK)
async def create_post_visit_feedback(
    case_id: uuid.UUID,
    data: PostVisitFeedbackRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _load_feedback_case(db, case_id, current_user, for_update=True)
    existing = await db.scalar(
        select(PatientPostVisitFeedback)
        .where(PatientPostVisitFeedback.case_id == case.id)
        .order_by(PatientPostVisitFeedback.version.desc())
        .limit(1)
    )
    if existing is not None:
        return {"created": False, "feedback": _post_visit_feedback_response(existing)}

    await _validate_feedback_materials(db, case, current_user, data.material_file_ids)
    payload = data.model_dump(mode="json")
    payload["revision_history"] = []
    row = PatientPostVisitFeedback(
        case_id=case.id,
        version=1,
        revision=1,
        payload=payload,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"created": True, "feedback": _post_visit_feedback_response(row)}


@router.patch("/cases/{case_id}/post-visit-feedback/{feedback_id}")
async def update_post_visit_feedback(
    case_id: uuid.UUID,
    feedback_id: uuid.UUID,
    data: PostVisitFeedbackUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _load_feedback_case(db, case_id, current_user, for_update=True)
    row = await db.scalar(
        select(PatientPostVisitFeedback)
        .where(
            PatientPostVisitFeedback.id == feedback_id,
            PatientPostVisitFeedback.case_id == case.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Post-visit feedback not found")
    if row.revision != data.expected_revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "message": "诊后回填已更新，请重新载入后再保存。"},
        )

    await _validate_feedback_materials(db, case, current_user, data.material_file_ids)
    old_payload = row.payload or {}
    history = list(old_payload.get("revision_history", []))
    history.append({
        "revision": row.revision,
        "submitted_at": row.updated_at.isoformat() if row.updated_at else None,
        "source_type": "patient_reported",
        "fields": {
            key: old_payload.get(key)
            for key in (
                "self_reported_visit_at", "actual_department", "patient_summary",
                "follow_up_items", "material_file_ids",
            )
        },
    })
    row.payload = {**data.model_dump(mode="json", exclude={"expected_revision"}), "revision_history": history}
    row.revision += 1
    await db.commit()
    await db.refresh(row)
    return _post_visit_feedback_response(row)


# ═══════════════════════════════════════════════════════════════
# Care Plans
# ═══════════════════════════════════════════════════════════════

@router.get("/care-plans")
async def list_care_plans(
    current_user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's care plans."""
    stmt = (
        select(CarePlan)
        .where(CarePlan.patient_id == current_user.id)
        .order_by(CarePlan.created_at.desc())
    )
    if status:
        stmt = stmt.where(CarePlan.status == status)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "description": p.description,
            "goals": [],
            "tasks": p.tasks or {},
            "status": p.status,
            "progress_percent": p.progress_percent or 0,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in result.scalars().all()
    ]


@router.get("/care-plans/{plan_id}")
async def get_care_plan(
    plan_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a specific care plan."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {
        "id": str(p.id),
        "title": p.title,
        "description": p.description,
        "diagnosis_summary": p.diagnosis_summary,
        "goals": [],
        "tasks": p.tasks or {},
        "status": p.status,
        "progress_percent": p.progress_percent or 0,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.post("/care-plans/{plan_id}/ack")
async def ack_task(
    plan_id: str,
    task_id: Annotated[str, Query(alias="task_id")],
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge (complete) a task in a care plan."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    tasks = plan.tasks or {}
    # Accept either dict tasks or AcknowledgeRequest body
    if task_id:
        if isinstance(tasks, dict) and "tasks" in tasks:
            for t in tasks["tasks"]:
                if t.get("id") == task_id:
                    t["status"] = "completed"
        elif isinstance(tasks, list):
            for t in tasks:
                if t.get("id") == task_id:
                    t["completed"] = True
    plan.tasks = tasks
    await db.commit()
    return {"success": True, "task_id": task_id}


# ═══════════════════════════════════════════════════════════════
# Reminders
# ═══════════════════════════════════════════════════════════════

@router.get("/reminders")
async def list_reminders(
    current_user: CurrentUser,
    status: Annotated[str | None, Query()] = "pending",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List patient's scheduled reminders."""
    stmt = (
        select(MonitoringEvent)
        .where(MonitoringEvent.patient_id == current_user.id)
        .order_by(MonitoringEvent.scheduled_at.desc())
    )
    if status:
        stmt = stmt.where(MonitoringEvent.status == status)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "payload": e.payload,
            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "status": e.status,
            "plan_id": str(e.plan_id) if e.plan_id else None,
        }
        for e in result.scalars().all()
    ]


@router.patch("/reminders/{reminder_id}/acknowledge")
async def acknowledge_reminder(
    reminder_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge a specific reminder."""
    result = await db.execute(
        select(MonitoringEvent).where(
            MonitoringEvent.id == reminder_id,
            MonitoringEvent.patient_id == current_user.id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Reminder not found")
    event.acknowledged_at = datetime.now(timezone.utc)
    event.status = "acknowledged"
    await db.commit()
    return {"success": True, "id": reminder_id}


# ═══════════════════════════════════════════════════════════════
# Check-in
# ═══════════════════════════════════════════════════════════════

class CheckInRequest(BaseModel):
    plan_id: str
    task_id: str
    value: float | None = None
    notes: str | None = None


@router.post("/check-in")
async def check_in(
    data: CheckInRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Patient check-in: mark a task as completed with optional value/notes."""
    result = await db.execute(
        select(CarePlan).where(
            CarePlan.id == data.plan_id,
            CarePlan.patient_id == current_user.id,
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    tasks = plan.tasks or {}
    if isinstance(tasks, dict) and "tasks" in tasks:
        for t in tasks["tasks"]:
            if t.get("id") == data.task_id:
                t["status"] = "completed"
                if data.value is not None:
                    t["last_value"] = data.value
                if data.notes:
                    t["notes"] = data.notes
    plan.tasks = tasks
    await db.commit()
    return {"success": True, "task_id": data.task_id, "task_status": "completed"}


@router.get("/reminders/count")
async def get_reminder_count(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get count of unacknowledged reminders for sidebar badge."""
    result = await db.execute(
        select(
            MonitoringEvent.event_type,
            func.count().label("count")
        ).where(
            MonitoringEvent.patient_id == current_user.id,
            MonitoringEvent.status == "sent",
            MonitoringEvent.acknowledged_at.is_(None),
        ).group_by(MonitoringEvent.event_type)
    )
    rows = result.all()
    counts = {"follow_up": 0, "medication": 0, "total": 0}
    for row in rows:
        if "medication" in row.event_type:
            counts["medication"] += row.count
        elif "follow_up" in row.event_type:
            counts["follow_up"] += row.count
    counts["total"] = counts["follow_up"] + counts["medication"]
    return counts


# ═══════════════════════════════════════════════════════════════
# Health Profile Refresh (triggers AI regeneration)
# ═══════════════════════════════════════════════════════════════

@router.post("/health-profile/refresh")
async def refresh_health_profile(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger AI to regenerate health summary from patient history."""
    from app.tasks.planning import generate_health_profile
    task = generate_health_profile.delay(str(current_user.id))
    return {"task_id": task.id, "message": "Health profile refresh started"}
