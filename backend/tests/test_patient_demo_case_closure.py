"""患者演示闭环的病例身份持久化契约。"""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent import AgentSession, AgentSessionType
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import CaseStatus, MedicalCase
from app.models.user import User, UserRole, UserStatus


def _patient(label: str) -> User:
    return User(
        email=f"{label}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name=label,
        role=UserRole.PATIENT,
        status=UserStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_diagnosis_case_is_created_once_and_source_material_is_bound(
    db_session: AsyncSession,
) -> None:
    from app.services.patient_case_persistence import persist_diagnosis_case

    patient = _patient("Demo Closure")
    db_session.add(patient)
    await db_session.flush()
    session = AgentSession(
        user_id=patient.id,
        session_type=AgentSessionType.DIAGNOSIS,
        context={"interview": {"chief_complaint": "合成主诉", "collected_info": {"duration": "2 天"}}},
    )
    db_session.add(session)
    await db_session.flush()
    material = DocumentParseTask(
        file_id=f"demo-{uuid.uuid4().hex}",
        filename="合成资料.txt",
        parse_method="file-extract",
        status="completed",
        file_bytes=b"synthetic demo material",
        owner_user_id=patient.id,
        source_session_id=session.id,
    )
    db_session.add(material)
    await db_session.commit()

    report = {"primary_diagnosis": "演示辅助报告", "severity": "mild", "red_flags": []}
    first = await persist_diagnosis_case(
        db_session,
        patient_id=patient.id,
        source_session_id=session.id,
        report=report,
        fallback_chief_complaint="备用主诉",
    )
    second = await persist_diagnosis_case(
        db_session,
        patient_id=patient.id,
        source_session_id=session.id,
        report=report,
        fallback_chief_complaint="备用主诉",
    )

    count = await db_session.scalar(
        select(func.count()).select_from(MedicalCase).where(MedicalCase.source_session_id == session.id)
    )
    await db_session.refresh(material)
    assert first.id == second.id
    assert first.patient_id == patient.id
    assert first.chief_complaint == "合成主诉"
    assert first.ai_diagnosis_summary == "演示辅助报告"
    assert first.status == CaseStatus.PENDING_REVIEW
    assert count == 1
    assert material.case_id == first.id


@pytest.mark.asyncio
async def test_concurrent_diagnosis_case_persistence_reuses_one_case(
    db_session: AsyncSession,
    test_engine,
) -> None:
    from app.services.patient_case_persistence import persist_diagnosis_case

    if not test_engine.url.drivername.startswith("postgresql"):
        pytest.skip("source row-lock contract requires PostgreSQL")

    patient = _patient("Concurrent Closure")
    db_session.add(patient)
    await db_session.flush()
    session = AgentSession(
        user_id=patient.id,
        session_type=AgentSessionType.DIAGNOSIS,
        context={"interview": {"chief_complaint": "合成并发主诉"}},
    )
    db_session.add(session)
    await db_session.commit()
    patient_id = patient.id
    source_session_id = session.id
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def persist_once() -> uuid.UUID:
        async with factory() as db:
            case = await persist_diagnosis_case(
                db,
                patient_id=patient_id,
                source_session_id=source_session_id,
                report={"primary_diagnosis": "并发合成报告", "severity": "unknown"},
                fallback_chief_complaint="备用合成主诉",
            )
            return case.id

    first_id, second_id = await asyncio.gather(persist_once(), persist_once())
    count = await db_session.scalar(
        select(func.count())
        .select_from(MedicalCase)
        .where(MedicalCase.source_session_id == source_session_id)
    )

    assert first_id == second_id
    assert count == 1


@pytest.mark.asyncio
async def test_diagnosis_case_rejects_source_session_owned_by_another_patient(
    db_session: AsyncSession,
) -> None:
    from app.services.patient_case_persistence import (
        DiagnosisCasePersistenceError,
        persist_diagnosis_case,
    )

    owner = _patient("Session Owner")
    other = _patient("Different Patient")
    db_session.add_all([owner, other])
    await db_session.flush()
    session = AgentSession(user_id=owner.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add(session)
    await db_session.commit()
    source_session_id = session.id

    with pytest.raises(DiagnosisCasePersistenceError, match="归属"):
        await persist_diagnosis_case(
            db_session,
            patient_id=other.id,
            source_session_id=source_session_id,
            report={"primary_diagnosis": "不可串号"},
            fallback_chief_complaint="合成主诉",
        )

    count = await db_session.scalar(
        select(func.count()).select_from(MedicalCase).where(MedicalCase.source_session_id == source_session_id)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_diagnosis_case_persistence_failure_rolls_back_and_is_explicit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.patient_case_persistence import (
        DiagnosisCasePersistenceError,
        persist_diagnosis_case,
    )

    patient = _patient("Persistence Failure")
    db_session.add(patient)
    await db_session.flush()
    session = AgentSession(user_id=patient.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add(session)
    await db_session.commit()
    source_session_id = session.id

    async def fail_commit() -> None:
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(DiagnosisCasePersistenceError, match="病例保存失败"):
        await persist_diagnosis_case(
            db_session,
            patient_id=patient.id,
            source_session_id=source_session_id,
            report={"primary_diagnosis": "演示报告"},
            fallback_chief_complaint="合成主诉",
        )

    await db_session.rollback()
    count = await db_session.scalar(
        select(func.count()).select_from(MedicalCase).where(MedicalCase.source_session_id == source_session_id)
    )
    assert count == 0
