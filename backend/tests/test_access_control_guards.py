"""离线验证身份、医生病例与解析结果的访问控制边界。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.v1 import auth, documents, doctor, medical_cases
from app.api.v1.admin import DoctorVerifyResponse
from app.models.user import UserRole
from app.models.document_parse import DocumentParseTask
from app.models.user import GuestSession
from app.schemas.auth import UserRegister


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


class _RegistrationDb:
    async def execute(self, _statement):
        return _EmptyResult()

    def add(self, _instance):
        pass

    async def commit(self):
        pass

    async def refresh(self, _instance):
        pass


def _registration(role: UserRole) -> UserRegister:
    return UserRegister(
        email=f"{role.value}@example.com",
        full_name="Test User",
        password="correct-horse-1",
        role=role,
    )


def test_public_registration_rejects_admin_before_database_access():
    async def attempt():
        return await auth.register(_registration(UserRole.ADMIN), db=object())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(attempt())
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", [UserRole.PATIENT, UserRole.DOCTOR])
def test_public_registration_keeps_patient_and_doctor_flows(role, monkeypatch):
    monkeypatch.setattr(auth, "get_password_hash", lambda _password: "test-hash")

    result = asyncio.run(auth.register(_registration(role), db=_RegistrationDb()))

    assert "注册成功" in result["message"] or "注册申请已提交" in result["message"]


def test_doctor_guard_rejects_other_roles_and_allows_doctor():
    patient_context = deps.UserContext(
        user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.PATIENT),
        platform="test",
    )
    doctor_user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.DOCTOR)
    doctor_context = deps.UserContext(user=doctor_user, platform="test")

    with pytest.raises(HTTPException) as exc:
        doctor._require_doctor(patient_context)
    assert exc.value.status_code == 403
    assert doctor._require_doctor(doctor_context) is doctor_user


def test_doctor_case_access_requires_the_assignment():
    assigned_doctor_id = uuid.uuid4()
    case = SimpleNamespace(assigned_doctor_id=assigned_doctor_id)
    assigned_doctor = SimpleNamespace(id=assigned_doctor_id)
    another_doctor = SimpleNamespace(id=uuid.uuid4())

    doctor._require_assigned_case(assigned_doctor, case)
    with pytest.raises(HTTPException) as exc:
        doctor._require_assigned_case(another_doctor, case)
    assert exc.value.status_code == 404

    case.patient_id = uuid.uuid4()
    another_doctor.role = UserRole.DOCTOR
    assert not medical_cases._can_access_case(another_doctor, case)
    case.assigned_doctor_id = another_doctor.id
    assert medical_cases._can_access_case(another_doctor, case)


def test_doctor_verification_response_matches_the_route_contract():
    approved = DoctorVerifyResponse(success=True, message="approved", action="approve")
    rejected = DoctorVerifyResponse(success=True, message="rejected", action="reject")
    assert approved.model_dump() == {
        "success": True,
        "message": "approved",
        "action": "approve",
    }
    assert rejected.action == "reject"


def test_parse_results_are_private_to_the_uploading_user_or_guest(monkeypatch):
    user_id = uuid.uuid4()
    guest_id = uuid.uuid4()
    user_task = DocumentParseTask(
        file_id="user-doc", status="completed", result={"ok": True}, owner_user_id=user_id
    )
    guest_task = DocumentParseTask(
        file_id="guest-doc", status="processing", owner_guest_id=guest_id
    )
    guest_session = SimpleNamespace(
        id=guest_id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    class ParseDb:
        tasks = {"user-doc": user_task, "guest-doc": guest_task}

        async def get(self, model, key):
            if model is DocumentParseTask:
                return self.tasks.get(key)
            if model is GuestSession and key == guest_id:
                return guest_session
            return None

        async def delete(self, task):
            self.tasks.pop(task.file_id, None)

        async def commit(self):
            return None

    db = ParseDb()
    owner = deps.UserContext(user=SimpleNamespace(id=user_id), platform="test")
    other_user = deps.UserContext(user=SimpleNamespace(id=uuid.uuid4()), platform="test")
    guest_owner = deps.UserContext(user=None, platform="test", is_guest=True, guest_id=str(guest_id))
    other_guest = deps.UserContext(
        user=None, platform="test", is_guest=True, guest_id=str(uuid.uuid4()),
    )

    assert asyncio.run(documents.get_parse_result("user-doc", owner, db=db))["result"] == {"ok": True}
    assert asyncio.run(documents.get_parse_result("guest-doc", guest_owner, db=db))["status"] == "processing"
    for file_id, context in (("user-doc", other_user), ("guest-doc", other_guest)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(documents.get_parse_result(file_id, context, db=db))
        assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        asyncio.run(documents.delete_document("user-doc", other_user, db=db))
    assert exc.value.status_code == 404
    asyncio.run(documents.delete_document("user-doc", owner, db=db))
    assert "user-doc" not in db.tasks
