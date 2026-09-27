"""T5 病例级诊后回填权限、修订与恢复。"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.agent import AgentSession, AgentSessionType
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import CaseStatus, MedicalCase
from app.models.user import User, UserRole, UserStatus


def _patient(label: str, role: UserRole = UserRole.PATIENT) -> User:
    return User(
        email=f"{label}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name=label,
        role=role,
        status=UserStatus.ACTIVE,
    )


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}"}


async def _case(db: AsyncSession, owner: User, title: str) -> MedicalCase:
    case = MedicalCase(
        patient_id=owner.id,
        title=title,
        status=CaseStatus.PENDING_REVIEW,
        doctor_diagnosis="医生原始诊断",
        doctor_notes="医生原始备注",
        treatment_plan={"doctor": "unchanged"},
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


@pytest.mark.asyncio
async def test_post_visit_feedback_persists_revisions_and_patient_materials(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T5 Owner")
    db_session.add(owner)
    await db_session.flush()
    case = await _case(db_session, owner, "T5 脱敏病例")
    source_session = AgentSession(
        user_id=owner.id,
        session_type=AgentSessionType.DIAGNOSIS,
        context={"_frontend_sid": "t5-session-linked-material"},
    )
    db_session.add(source_session)
    await db_session.flush()
    case.source_session_id = source_session.id
    material = DocumentParseTask(
        file_id=f"t5-{uuid.uuid4().hex}",
        filename="复查记录.pdf",
        mime_type="application/pdf",
        parse_method="medical_record",
        status="completed",
        file_bytes=b"synthetic test material",
        result={"summary": "synthetic"},
        owner_user_id=owner.id,
        client_session_id="t5-session-linked-material",
    )
    db_session.add(material)
    await db_session.commit()

    url = f"/api/v1/patient/cases/{case.id}/post-visit-feedback"
    fields = {
        "self_reported_visit_at": "2026-09-25T10:30:00+08:00",
        "actual_department": "患者自述科室",
        "patient_summary": "医生查看了复查结果。",
        "follow_up_items": ["患者自述：下次复查"],
        "material_file_ids": [material.file_id],
    }
    created = await client.post(url, headers=_headers(owner), json=fields)
    duplicate = await client.post(url, headers=_headers(owner), json={**fields, "patient_summary": "不应覆盖"})
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert created.json()["feedback"]["source_type"] == "patient_reported"
    assert duplicate.json()["created"] is False
    assert duplicate.json()["feedback"]["patient_summary"] == fields["patient_summary"]

    updated = await client.patch(
        f"{url}/{created.json()['feedback']['feedback_id']}",
        headers=_headers(owner),
        json={**fields, "expected_revision": 1, "patient_summary": "患者修订后的自述。"},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["revision_history"][0]["fields"]["patient_summary"] == fields["patient_summary"]
    conflict = await client.patch(
        f"{url}/{created.json()['feedback']['feedback_id']}",
        headers=_headers(owner),
        json={**fields, "expected_revision": 1},
    )
    assert conflict.status_code == 409

    recovered = await client.get(url, headers=_headers(owner))
    assert recovered.status_code == 200
    assert recovered.json()["feedback"]["revision"] == 2
    assert recovered.json()["feedback"]["patient_summary"] == "患者修订后的自述。"
    assert recovered.json()["feedback"]["material_file_ids"] == [material.file_id]
    assert recovered.json()["feedback"]["revision_history"][0]["source_type"] == "patient_reported"

    await db_session.refresh(case)
    assert case.doctor_diagnosis == "医生原始诊断"
    assert case.doctor_notes == "医生原始备注"
    assert case.treatment_plan == {"doctor": "unchanged"}
    assert case.follow_up_due_at is None


@pytest.mark.asyncio
async def test_post_visit_feedback_enforces_case_patient_role_and_material_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T5 Permission Owner")
    other = _patient("T5 Permission Other")
    doctor = _patient("T5 Permission Doctor", UserRole.DOCTOR)
    db_session.add_all([owner, other, doctor])
    await db_session.flush()
    own_case = await _case(db_session, owner, "本人病例")
    other_case = await _case(db_session, other, "其他患者病例")
    fields = {"patient_summary": "患者自述内容"}
    url = f"/api/v1/patient/cases/{own_case.id}/post-visit-feedback"

    cross_case_material = DocumentParseTask(
        file_id=f"t5-other-{uuid.uuid4().hex}",
        filename="他人材料.pdf",
        parse_method="medical_record",
        status="queued",
        file_bytes=b"synthetic",
        owner_user_id=owner.id,
        case_id=other_case.id,
    )
    other_patient_material = DocumentParseTask(
        file_id=f"t5-owner-{uuid.uuid4().hex}",
        filename="他人患者材料.pdf",
        parse_method="medical_record",
        status="queued",
        file_bytes=b"synthetic",
        owner_user_id=other.id,
        case_id=own_case.id,
    )
    db_session.add_all([cross_case_material, other_patient_material])
    await db_session.commit()

    invalid_material = await client.post(
        url,
        headers=_headers(owner),
        json={**fields, "material_file_ids": [cross_case_material.file_id]},
    )
    other_invalid_material = await client.post(
        url,
        headers=_headers(owner),
        json={**fields, "material_file_ids": [other_patient_material.file_id]},
    )
    denied = await client.get(url, headers=_headers(other))
    doctor_denied = await client.get(url, headers=_headers(doctor))
    assert invalid_material.status_code == 422
    assert other_invalid_material.status_code == 422
    assert denied.status_code == 404
    assert doctor_denied.status_code == 404
    assert (await client.get(url, headers=_headers(owner))).json()["feedback"] is None
