"""Medical case and document endpoints.

Permission matrix:
- Patient: CRUD own cases, CRUD own documents.
- Doctor: Read/write assigned cases, add/update diagnosis.
- Admin: Full access.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.agent import AgentSession
from app.models.medical_case import CaseStatus, DocumentType, MedicalCase, MedicalDocument
from app.models.user import UserRole
from app.schemas.medical_case import (
    MedicalCaseCreate,
    MedicalCaseDoctorUpdate,
    MedicalCaseListResponse,
    MedicalCaseResponse,
    MedicalCaseUpdate,
    MedicalDocumentCreate,
    MedicalDocumentResponse,
    MedicalDocumentUpdate,
)

router = APIRouter()


async def _get_case(
    case_id: uuid.UUID,
    db: AsyncSession,
) -> MedicalCase:
    """Fetch a case by ID or raise 404."""
    result = await db.execute(
        select(MedicalCase).where(MedicalCase.id == case_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medical case '{case_id}' not found",
        )
    return case


def _can_access_case(current_user, case: MedicalCase) -> bool:
    """Check if user can access a case."""
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.role == UserRole.PATIENT:
        return case.patient_id == current_user.id
    if current_user.role == UserRole.DOCTOR:
        return case.assigned_doctor_id == current_user.id
    return False


def _can_modify_case(current_user, case: MedicalCase) -> bool:
    """Check if user can modify a case."""
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.role == UserRole.PATIENT:
        return case.patient_id == current_user.id and case.status not in {
            CaseStatus.RESOLVED,
            CaseStatus.ARCHIVED,
        }
    if current_user.role == UserRole.DOCTOR:
        return case.assigned_doctor_id == current_user.id
    return False


# ─── Medical Cases ───────────────────────────────────────────


@router.get("", response_model=MedicalCaseListResponse)
async def list_cases(
    current_user: CurrentUser,
    status: Annotated[CaseStatus | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: AsyncSession = Depends(get_db),
) -> MedicalCaseListResponse:
    """List medical cases visible to the current user."""
    stmt = select(MedicalCase)

    if current_user.role == UserRole.PATIENT:
        stmt = stmt.where(MedicalCase.patient_id == current_user.id)
    elif current_user.role == UserRole.DOCTOR:
        stmt = stmt.where(
            MedicalCase.assigned_doctor_id == current_user.id
        )
    # Admin sees all

    if status:
        stmt = stmt.where(MedicalCase.status == status)

    # Count total
    count_stmt = select(func.count(MedicalCase.id))
    if current_user.role == UserRole.PATIENT:
        count_stmt = count_stmt.where(MedicalCase.patient_id == current_user.id)
    elif current_user.role == UserRole.DOCTOR:
        count_stmt = count_stmt.where(
            MedicalCase.assigned_doctor_id == current_user.id
        )
    if status:
        count_stmt = count_stmt.where(MedicalCase.status == status)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Fetch paginated
    stmt = stmt.order_by(MedicalCase.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    cases = result.scalars().all()

    return MedicalCaseListResponse(
        total=total,
        items=[MedicalCaseResponse.model_validate(c) for c in cases],
    )


@router.post("", response_model=MedicalCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_case(
    data: MedicalCaseCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalCaseResponse:
    """Create a new medical case (patient creates for themselves)."""
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can create their own cases",
        )

    if data.source_session_id is not None:
        source_session = await db.scalar(
            select(AgentSession).where(AgentSession.id == data.source_session_id)
        )
        if source_session is None or source_session.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source session not found",
            )

    case = MedicalCase(
        patient_id=current_user.id,
        title=data.title,
        description=data.description,
        status=data.status,
        chief_complaint=data.chief_complaint,
        ai_diagnosis_summary=data.ai_diagnosis_summary,
        severity=data.severity,
        is_emergency=data.is_emergency,
        source_session_id=data.source_session_id,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return MedicalCaseResponse.model_validate(case)


@router.get("/{case_id}", response_model=MedicalCaseResponse)
async def get_case(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalCaseResponse:
    """Get a single medical case."""
    case = await _get_case(case_id, db)
    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this case",
        )
    return MedicalCaseResponse.model_validate(case)


@router.patch("/{case_id}", response_model=MedicalCaseResponse)
async def update_case(
    case_id: uuid.UUID,
    data: MedicalCaseUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalCaseResponse:
    """Update a medical case."""
    case = await _get_case(case_id, db)
    if not _can_modify_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this case",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(case, field, value)

    await db.commit()
    await db.refresh(case)
    return MedicalCaseResponse.model_validate(case)


@router.patch("/{case_id}/diagnosis", response_model=MedicalCaseResponse)
async def update_diagnosis(
    case_id: uuid.UUID,
    data: MedicalCaseDoctorUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalCaseResponse:
    """Doctor updates diagnosis for a case."""
    case = await _get_case(case_id, db)

    if current_user.role not in (UserRole.DOCTOR, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can update diagnosis",
        )

    if current_user.role == UserRole.DOCTOR and case.assigned_doctor_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this case",
        )

    if data.assigned_doctor_id is not None:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can assign a doctor to this case",
            )
        case.assigned_doctor_id = data.assigned_doctor_id
    if data.doctor_diagnosis is not None:
        case.doctor_diagnosis = data.doctor_diagnosis
    if data.doctor_notes is not None:
        case.doctor_notes = data.doctor_notes
    if data.treatment_plan is not None:
        case.treatment_plan = data.treatment_plan
    if data.follow_up_due_at is not None:
        case.follow_up_due_at = data.follow_up_due_at
    if data.status is not None:
        case.status = data.status
        from datetime import datetime, timezone
        case.resolved_at = datetime.now(timezone.utc) if data.status == CaseStatus.RESOLVED else None

    await db.commit()
    await db.refresh(case)
    return MedicalCaseResponse.model_validate(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a medical case."""
    case = await _get_case(case_id, db)
    if not _can_modify_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this case",
        )
    await db.delete(case)
    await db.commit()


# ─── Medical Documents ───────────────────────────────────────────


@router.post("/{case_id}/documents", response_model=MedicalDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    case_id: uuid.UUID,
    data: MedicalDocumentCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalDocumentResponse:
    """Add a document to a medical case."""
    case = await _get_case(case_id, db)
    if not _can_modify_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to add documents to this case",
        )

    doc = MedicalDocument(
        case_id=case_id,
        uploaded_by=current_user.id,
        document_type=data.document_type,
        title=data.title,
        file_path=data.file_path,
        file_size=data.file_size,
        mime_type=data.mime_type,
        content_text=data.content_text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return MedicalDocumentResponse.model_validate(doc)


@router.get("/{case_id}/documents/{doc_id}", response_model=MedicalDocumentResponse)
async def get_document(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalDocumentResponse:
    """Get a specific document."""
    case = await _get_case(case_id, db)
    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this case",
        )

    result = await db.execute(
        select(MedicalDocument).where(
            MedicalDocument.id == doc_id,
            MedicalDocument.case_id == case_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in case '{case_id}'",
        )
    return MedicalDocumentResponse.model_validate(doc)


@router.patch("/{case_id}/documents/{doc_id}", response_model=MedicalDocumentResponse)
async def update_document(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    data: MedicalDocumentUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MedicalDocumentResponse:
    """Update a document."""
    case = await _get_case(case_id, db)
    if not _can_modify_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify documents in this case",
        )

    result = await db.execute(
        select(MedicalDocument).where(
            MedicalDocument.id == doc_id,
            MedicalDocument.case_id == case_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in case '{case_id}'",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doc, field, value)

    await db.commit()
    await db.refresh(doc)
    return MedicalDocumentResponse.model_validate(doc)


@router.delete("/{case_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    case_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document."""
    case = await _get_case(case_id, db)
    if not _can_modify_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete documents in this case",
        )

    result = await db.execute(
        select(MedicalDocument).where(
            MedicalDocument.id == doc_id,
            MedicalDocument.case_id == case_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in case '{case_id}'",
        )

    await db.delete(doc)
    await db.commit()
