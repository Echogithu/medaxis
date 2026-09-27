"""T4 就医准备快照、核对、版本与权限合同。"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.agent import AgentSession, AgentSessionType, PatientHealthProfile
from app.models.case_preparation import CasePreparationPackage
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


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id), platform="web")
    return {"Authorization": f"Bearer {token}"}


async def _case_for(db: AsyncSession, owner: User) -> tuple[MedicalCase, AgentSession]:
    session = AgentSession(
        user_id=owner.id,
        session_type=AgentSessionType.DIAGNOSIS,
        context={"interview": {"collected_info": {"症状经过": "间歇性头痛"}}},
        structured_output={
            "primary_diagnosis": "AI 初步分析",
            "key_findings": ["报告中的待核查发现"],
            "knowledge_sources": ["仅有来源名称，缺少可验证定位"],
        },
    )
    db.add(session)
    await db.flush()
    case = MedicalCase(
        patient_id=owner.id,
        source_session_id=session.id,
        title="脱敏头痛病例",
        chief_complaint="头痛",
        ai_diagnosis_summary="AI 初步分析",
        status=CaseStatus.PENDING_REVIEW,
    )
    db.add(case)
    await db.commit()
    return case, session


@pytest.mark.asyncio
async def test_preparation_is_persisted_idempotent_and_keeps_patient_corrections(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T4 Owner")
    db_session.add(owner)
    await db_session.flush()
    case, source_session = await _case_for(db_session, owner)
    url = f"/api/v1/patient/cases/{case.id}/preparation"
    headers = _headers(owner)

    created = await client.post(url, headers=headers)
    repeated = await client.post(url, headers=headers)
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert repeated.json()["created"] is False
    assert repeated.json()["package_id"] == created.json()["package_id"]
    assert created.json()["department"]["status"] == "insufficient_evidence"
    assert created.json()["unknown_facts"] == [
        {"id": "unknown.allergies", "label": "过敏史", "status": "unknown"},
        {"id": "unknown.medications", "label": "当前用药", "status": "unknown"},
    ]

    recovered = await client.get(url, headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["package"]["package_id"] == created.json()["package_id"]
    assert recovered.json()["package"]["summary"]["ai_inference"] == [
        "AI 初步分析", "报告中的待核查发现"
    ]

    package_id = created.json()["package_id"]
    changed = await client.patch(
        f"{url}/{package_id}",
        headers=headers,
        json={
            "expected_revision": 1,
            "confirmed_fact_ids": ["patient.chief_complaint"],
            "patient_corrections": [
                {"fact_id": "unknown.allergies", "value": "患者更正：青霉素过敏"},
                {"fact_id": "patient.chief_complaint", "value": "患者更正：头痛已持续三天"},
            ],
            "patient_questions": ["复诊时需要带哪些资料？"],
            "checklist_updates": [{"item_id": "prepare.questions", "status": "ready"}],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    assert changed.json()["state"] == "needs_reassessment"
    await db_session.refresh(case)
    await db_session.refresh(source_session)
    assert case.chief_complaint == "头痛"
    assert source_session.context["interview"]["collected_info"]["症状经过"] == "间歇性头痛"

    regenerated = await client.post(url, headers=headers)
    assert regenerated.status_code == 200
    assert regenerated.json()["created"] is True
    assert regenerated.json()["version"] == 2
    assert regenerated.json()["patient_questions"] == ["复诊时需要带哪些资料？"]
    assert any(
        fact["source_type"] == "patient_correction"
        and fact["value"] == "患者更正：青霉素过敏"
        for fact in regenerated.json()["known_facts"]
    )
    assert all(fact["id"] != "unknown.allergies" for fact in regenerated.json()["unknown_facts"])
    assert next(
        fact for fact in regenerated.json()["known_facts"]
        if fact["id"] == "patient.chief_complaint"
    )["active"] is False
    recovered = await client.get(url, headers=headers)
    assert recovered.json()["package"]["version"] == 2
    assert recovered.json()["history"][0]["version"] == 1
    assert recovered.json()["history"][0]["is_stale"] is True

    source_session.structured_output = {
        **source_session.structured_output,
        "key_findings": ["来源报告已修订"],
    }
    await db_session.commit()
    assert (await client.get(url, headers=headers)).json()["package"]["is_stale"] is True
    source_updated = await client.post(url, headers=headers)
    assert source_updated.status_code == 200
    assert source_updated.json()["version"] == 3
    assert source_updated.json()["summary"]["ai_inference"][-1] == "来源报告已修订"


@pytest.mark.asyncio
async def test_preparation_enforces_owner_and_compare_and_swap(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T4 Permission Owner")
    other = _patient("T4 Permission Other")
    doctor = User(
        email=f"doctor-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name="T4 Doctor",
        role=UserRole.DOCTOR,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([owner, other, doctor])
    await db_session.flush()
    case, _ = await _case_for(db_session, owner)
    url = f"/api/v1/patient/cases/{case.id}/preparation"
    created = await client.post(url, headers=_headers(owner))
    package_id = created.json()["package_id"]

    denied = await client.get(url, headers=_headers(other))
    doctor_denied = await client.get(url, headers=_headers(doctor))
    denied_patch = await client.patch(
        f"{url}/{package_id}",
        headers=_headers(other),
        json={"expected_revision": 1},
    )
    conflict = await client.patch(
        f"{url}/{package_id}",
        headers=_headers(owner),
        json={"expected_revision": 99},
    )

    assert denied.status_code == 404
    assert doctor_denied.status_code == 404
    assert denied_patch.status_code == 404
    assert conflict.status_code == 409
    rows = await db_session.scalars(
        select(CasePreparationPackage).where(CasePreparationPackage.case_id == case.id)
    )
    assert len(list(rows)) == 1


@pytest.mark.asyncio
async def test_preparation_requires_report_but_does_not_hide_existing_case(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T4 No Report")
    db_session.add(owner)
    await db_session.flush()
    case = MedicalCase(patient_id=owner.id, title="仍可读取的病例")
    db_session.add(case)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/patient/cases/{case.id}/preparation", headers=_headers(owner)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "report_not_ready"
    assert case.title == "仍可读取的病例"


@pytest.mark.asyncio
async def test_preparation_includes_patient_profile_and_unverified_source_names(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T4 Profile Source")
    db_session.add(owner)
    await db_session.flush()
    case, _ = await _case_for(db_session, owner)
    profile = PatientHealthProfile(
        patient_id=owner.id,
        allergies=["青霉素"],
        current_medications=[{"name": "示例药物", "dosage": "按本人记录"}],
    )
    db_session.add(profile)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/patient/cases/{case.id}/preparation", headers=_headers(owner)
    )

    assert response.status_code == 200
    package = response.json()
    profile_facts = {
        fact["source_id"]: fact
        for fact in package["known_facts"]
        if fact["source_id"].startswith("patient_profile.")
    }
    assert profile_facts["patient_profile.allergies"]["value"] == ["青霉素"]
    assert profile_facts["patient_profile.current_medications"]["value"][0]["name"] == "示例药物"
    assert all(fact["source_type"] == "patient_reported" for fact in profile_facts.values())
    assert package["unknown_facts"] == []
    assert {item["id"] for item in package["source_index"]} >= {
        "patient_profile.allergies", "patient_profile.current_medications", "source_session.report"
    }
    assert package["unverified_knowledge_sources"] == [{
        "name": "仅有来源名称，缺少可验证定位",
        "verified_citation": False,
        "note": "当前报告仅保存来源名称，缺少发布机构、版本和原文定位。",
    }]

    url = f"/api/v1/patient/cases/{case.id}/preparation"
    package_id = package["package_id"]
    first_revision = await client.patch(
        f"{url}/{package_id}",
        headers=_headers(owner),
        json={
            "expected_revision": 1,
            "confirmed_fact_ids": ["patient.profile.allergies"],
            "patient_corrections": [
                {"fact_id": "patient.profile.allergies", "value": "本人更正：无已知过敏"}
            ],
        },
    )
    assert first_revision.status_code == 200
    unconfirmed = await client.patch(
        f"{url}/{package_id}",
        headers=_headers(owner),
        json={"expected_revision": 2, "confirmed_fact_ids": []},
    )
    assert unconfirmed.status_code == 200
    assert next(
        fact for fact in unconfirmed.json()["known_facts"]
        if fact["id"] == "patient.profile.allergies"
    )["confirmed"] is False

    profile.allergies = ["磺胺"]
    await db_session.commit()
    refreshed = await client.post(url, headers=_headers(owner))
    updated_allergy = next(
        fact for fact in refreshed.json()["known_facts"]
        if fact["id"] == "patient.profile.allergies"
    )
    assert updated_allergy["value"] == ["磺胺"]
    assert updated_allergy["active"] is True
    assert updated_allergy["confirmed"] is False
    assert refreshed.json()["patient_corrections"] == []


@pytest.mark.asyncio
async def test_preparation_save_failure_keeps_last_committed_version(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _patient("T4 Save Failure")
    db_session.add(owner)
    await db_session.flush()
    case, _ = await _case_for(db_session, owner)
    url = f"/api/v1/patient/cases/{case.id}/preparation"
    created = await client.post(url, headers=_headers(owner))
    package_id = uuid.UUID(created.json()["package_id"])
    row = await db_session.get(CasePreparationPackage, package_id)
    assert row is not None

    original_commit = db_session.commit

    async def fail_commit() -> None:
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    from app.api.v1.patient import PreparationUpdateRequest, update_case_preparation

    with pytest.raises(RuntimeError, match="synthetic database outage"):
        await update_case_preparation(
            case_id=case.id,
            package_id=package_id,
            data=PreparationUpdateRequest(
                expected_revision=1,
                checklist_updates=[{"item_id": "prepare.questions", "status": "ready"}],
            ),
            current_user=owner,
            db=db_session,
        )
    monkeypatch.setattr(db_session, "commit", original_commit)
    await db_session.rollback()
    await db_session.refresh(row)

    assert row.revision == 1
    assert row.package["preparation_items"][-1]["status"] == "pending"
