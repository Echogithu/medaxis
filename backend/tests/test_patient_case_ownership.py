"""通用病例创建入口必须保持患者与诊断会话归属一致。"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.medical_cases import create_case
from app.models.agent import AgentSession, AgentSessionType
from app.models.user import User, UserRole
from app.schemas.medical_case import MedicalCaseCreate


class _FakeSession:
    def __init__(self, source_session: AgentSession | None = None) -> None:
        self.source_session = source_session
        self.statement = None
        self.added: list[object] = []
        self.committed = False

    async def scalar(self, statement):
        self.statement = statement
        return self.source_session

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _value: object) -> None:
        _value.id = uuid.uuid4()
        _value.created_at = datetime.now(timezone.utc)
        _value.updated_at = _value.created_at


def _user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name="Synthetic user",
        role=role,
    )


def _assert_source_session_lookup(db: _FakeSession, source_session_id: uuid.UUID) -> None:
    assert db.statement is not None
    assert db.statement.column_descriptions[0]["entity"] is AgentSession
    condition = db.statement.whereclause
    assert condition.left.key == "id"
    assert condition.left.table.name == AgentSession.__tablename__
    assert condition.right.value == source_session_id


@pytest.mark.asyncio
async def test_patient_cannot_create_case_from_another_users_session() -> None:
    owner = _user(UserRole.PATIENT)
    other = _user(UserRole.PATIENT)
    source = AgentSession(
        id=uuid.uuid4(), user_id=owner.id, session_type=AgentSessionType.DIAGNOSIS
    )
    db = _FakeSession(source)

    with pytest.raises(HTTPException) as error:
        await create_case(
            MedicalCaseCreate(title="synthetic case", source_session_id=source.id),
            other,
            db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Source session not found"
    _assert_source_session_lookup(db, source.id)
    assert db.added == []
    assert db.committed is False


@pytest.mark.asyncio
async def test_patient_cannot_create_case_from_missing_session() -> None:
    patient = _user(UserRole.PATIENT)
    missing_source_id = uuid.uuid4()
    db = _FakeSession()

    with pytest.raises(HTTPException) as error:
        await create_case(
            MedicalCaseCreate(title="synthetic case", source_session_id=missing_source_id),
            patient,
            db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Source session not found"
    _assert_source_session_lookup(db, missing_source_id)
    assert db.added == []
    assert db.committed is False


@pytest.mark.asyncio
async def test_patient_can_create_case_from_own_session() -> None:
    patient = _user(UserRole.PATIENT)
    source = AgentSession(
        id=uuid.uuid4(), user_id=patient.id, session_type=AgentSessionType.DIAGNOSIS
    )
    db = _FakeSession(source)

    response = await create_case(
        MedicalCaseCreate(title="synthetic case", source_session_id=source.id),
        patient,
        db,
    )

    assert response.patient_id == patient.id
    assert response.source_session_id == source.id
    _assert_source_session_lookup(db, source.id)
    assert db.committed is True
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_non_patient_cannot_create_patient_case() -> None:
    doctor = _user(UserRole.DOCTOR)
    db = _FakeSession()

    with pytest.raises(HTTPException) as error:
        await create_case(MedicalCaseCreate(title="synthetic case"), doctor, db)

    assert error.value.status_code == 403
    assert db.added == []
    assert db.committed is False
