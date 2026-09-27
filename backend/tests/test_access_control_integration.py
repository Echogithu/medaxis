"""数据库/API 边界的身份与病例访问控制回归测试。"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.v1 import documents
from app.core.security import create_access_token, create_guest_token
from app.models.medical_case import MedicalCase
from app.models.document_parse import DocumentParseTask
from app.models.user import GuestSession, User, UserRole, UserStatus
from datetime import datetime, timedelta, timezone


@pytest.fixture(autouse=True)
def _disable_token_blacklist_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RedisWithoutRevokedTokens:
        async def get(self, _key: str) -> None:
            return None

    monkeypatch.setattr(deps, "get_redis", _RedisWithoutRevokedTokens)


def _new_user(role: UserRole, label: str) -> User:
    return User(
        email=f"{label}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name=label,
        role=role,
        status=UserStatus.ACTIVE,
    )


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id), platform="web")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_assigned_doctor_can_read_case_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    patient = _new_user(UserRole.PATIENT, "Test Patient")
    doctor = _new_user(UserRole.DOCTOR, "Assigned Doctor")
    another_doctor = _new_user(UserRole.DOCTOR, "Unassigned Doctor")
    db_session.add_all([patient, doctor, another_doctor])
    await db_session.flush()

    case = MedicalCase(
        patient_id=patient.id,
        assigned_doctor_id=doctor.id,
        title="Case for assigned doctor",
        description="A test case",
    )
    db_session.add(case)
    await db_session.commit()

    doctor_headers = _auth_header(doctor)
    response = await client.get(
        f"/api/v1/doctor/cases/{case.id}",
        headers=doctor_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(case.id)

    list_response = await client.get(
        "/api/v1/doctor/cases",
        headers=doctor_headers,
    )

    assert list_response.status_code == 200
    assert any(item["id"] == str(case.id) for item in list_response.json())

    patient_response = await client.get(
        "/api/v1/doctor/cases", headers=_auth_header(patient)
    )
    assert patient_response.status_code == 403

    other_doctor_headers = _auth_header(another_doctor)
    other_detail = await client.get(
        f"/api/v1/doctor/cases/{case.id}", headers=other_doctor_headers
    )
    assert other_detail.status_code == 404

    other_plan = await client.post(
        f"/api/v1/doctor/cases/{case.id}/plan",
        json={"instruction": "review"},
        headers=other_doctor_headers,
    )
    assert other_plan.status_code == 404

    assigned_diagnosis = await client.patch(
        f"/api/v1/medical-cases/{case.id}/diagnosis",
        json={"doctor_diagnosis": "Reviewed diagnosis"},
        headers=doctor_headers,
    )
    assert assigned_diagnosis.status_code == 200
    assert assigned_diagnosis.json()["doctor_diagnosis"] == "Reviewed diagnosis"

    unassigned_diagnosis = await client.patch(
        f"/api/v1/medical-cases/{case.id}/diagnosis",
        json={"doctor_diagnosis": "Unauthorized change"},
        headers=other_doctor_headers,
    )
    assert unassigned_diagnosis.status_code == 403


@pytest.mark.asyncio
async def test_public_registration_rejects_admin_without_creating_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = f"public-admin-{uuid.uuid4()}@example.com"

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Public Admin",
            "password": "correct-horse-1",
            "role": "admin",
        },
    )

    assert response.status_code == 403
    result = await db_session.execute(select(User).where(User.email == email))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_parse_results_are_private_across_user_and_guest_sessions(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _new_user(UserRole.PATIENT, "Report Owner")
    other_user = _new_user(UserRole.PATIENT, "Other User")
    guest_id = uuid.uuid4()
    other_guest_id = str(uuid.uuid4())
    guest = GuestSession(
        session_token=f"session-{uuid.uuid4()}",
        fingerprint="report-owner",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add_all([owner, other_user, guest])
    await db_session.flush()
    user_task = DocumentParseTask(
        file_id="user-report",
        filename="user.txt",
        parse_method="file-extract",
        status="completed",
        file_bytes=b"private",
        result={"summary": "private"},
        owner_user_id=owner.id,
    )
    guest_task = DocumentParseTask(
        file_id="guest-report",
        filename="guest.txt",
        parse_method="file-extract",
        status="processing",
        file_bytes=b"guest",
        owner_guest_id=guest.id,
    )
    db_session.add_all([user_task, guest_task])
    await db_session.commit()

    owner_headers = _auth_header(owner)
    other_user_headers = _auth_header(other_user)
    guest_headers = {
        "X-Guest-Token": create_guest_token(str(guest.id), platform="web")
    }
    other_guest_headers = {
        "X-Guest-Token": create_guest_token(other_guest_id, platform="web")
    }

    owner_result = await client.get(
        "/api/v1/documents/user-report/result", headers=owner_headers
    )
    assert owner_result.status_code == 200

    other_user_result = await client.get(
        "/api/v1/documents/user-report/result", headers=other_user_headers
    )
    assert other_user_result.status_code == 404
    other_user_delete = await client.delete(
        "/api/v1/documents/user-report", headers=other_user_headers
    )
    assert other_user_delete.status_code == 404

    guest_result = await client.get(
        "/api/v1/documents/guest-report/result", headers=guest_headers
    )
    assert guest_result.status_code == 200
    other_guest_result = await client.get(
        "/api/v1/documents/guest-report/result", headers=other_guest_headers
    )
    assert other_guest_result.status_code == 404
    other_guest_delete = await client.delete(
        "/api/v1/documents/guest-report", headers=other_guest_headers
    )
    assert other_guest_delete.status_code == 404

    user_to_guest = await client.get(
        "/api/v1/documents/guest-report/result", headers=owner_headers
    )
    guest_to_user = await client.get(
        "/api/v1/documents/user-report/result", headers=guest_headers
    )
    assert user_to_guest.status_code == 404
    assert guest_to_user.status_code == 404

    owner_delete = await client.delete(
        "/api/v1/documents/user-report", headers=owner_headers
    )
    guest_delete = await client.delete(
        "/api/v1/documents/guest-report", headers=guest_headers
    )
    assert owner_delete.status_code == 204
    assert guest_delete.status_code == 204
