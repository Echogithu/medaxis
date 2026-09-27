"""T3 persistence and ownership regression tests."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import documents
from app.core.security import create_access_token, create_guest_token
from app.models.document_parse import DocumentParseTask
from app.models.agent import AgentSession, AgentSessionType
from app.models.medical_case import CaseStatus, MedicalCase
from app.models.user import GuestSession, User, UserRole, UserStatus


def _patient(label: str) -> User:
    return User(
        email=f"{label}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name=label,
        role=UserRole.PATIENT,
        status=UserStatus.ACTIVE,
    )


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}"}


@pytest.mark.asyncio
async def test_parse_result_remains_queryable_after_process_cache_is_lost(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _patient("T3 Owner")
    db_session.add(owner)
    await db_session.commit()

    from app.tasks.documents import process_document_parse

    monkeypatch.setattr(process_document_parse, "delay", lambda *_args: None)
    uploaded = await client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(owner),
        files={"file": ("blood-test.txt", b"hemoglobin, 12", "text/plain")},
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["file_id"]

    # Replacing process-local state simulates a fresh API process.
    monkeypatch.setattr(documents, "_parse_tasks", {}, raising=False)
    recovered = await client.get(
        f"/api/v1/documents/{file_id}/result", headers=_auth_header(owner)
    )

    assert recovered.status_code == 200
    assert recovered.json()["status"] in {"queued", "processing"}


@pytest.mark.asyncio
async def test_lab_report_write_rejects_a_session_owned_by_another_patient(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T3 Session Owner")
    other = _patient("T3 Other Patient")
    db_session.add_all([owner, other])
    await db_session.flush()
    session = AgentSession(user_id=owner.id, session_type=AgentSessionType.DIAGNOSIS)
    other_session = AgentSession(user_id=other.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add_all([session, other_session])
    file_id = f"owners-report-{uuid.uuid4()}"
    task = DocumentParseTask(
        file_id=file_id,
        filename="report.txt",
        parse_method="file-extract",
        status="completed",
        file_bytes=b"private",
        result={"file_id": file_id, "indicators": []},
        owner_user_id=owner.id,
    )
    db_session.add(task)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/agents/sessions/{session.id}/lab-reports",
        headers=_auth_header(other),
        json=[{"file_id": task.file_id, "indicators": []}],
    )

    assert response.status_code == 404

    wrong_session = await client.post(
        f"/api/v1/agents/sessions/{other_session.id}/lab-reports",
        headers=_auth_header(owner),
        json=[{"file_id": task.file_id}],
    )
    assert wrong_session.status_code == 404

    accepted = await client.post(
        f"/api/v1/agents/sessions/{session.id}/lab-reports",
        headers=_auth_header(owner),
        json=[{"file_id": task.file_id}],
    )
    repeated = await client.post(
        f"/api/v1/agents/sessions/{session.id}/lab-reports",
        headers=_auth_header(owner),
        json=[{"file_id": task.file_id}],
    )
    assert accepted.status_code == 200
    assert repeated.json()["count"] == 1
    await db_session.refresh(session)
    assert len(session.context["lab_reports"]) == 1


@pytest.mark.asyncio
async def test_session_continue_rejects_missing_or_wrong_owner_before_streaming(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T3 Continue Owner")
    other = _patient("T3 Continue Other")
    db_session.add_all([owner, other])
    await db_session.flush()
    session = AgentSession(user_id=owner.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add(session)
    await db_session.commit()

    url = "/api/v1/agents/route/stream/continue"
    params = {"session_id": str(session.id), "question_id": "q1", "answer": "x"}
    anonymous = await client.post(url, params=params)
    wrong_owner = await client.post(url, params=params, headers=_auth_header(other))

    assert anonymous.status_code == 404
    assert wrong_owner.status_code == 404


@pytest.mark.asyncio
async def test_post_diagnosis_chat_rejects_missing_or_wrong_owner(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T3 Chat Owner")
    other = _patient("T3 Chat Other")
    db_session.add_all([owner, other])
    await db_session.flush()
    session = AgentSession(
        user_id=owner.id,
        session_type=AgentSessionType.DIAGNOSIS,
        context={"interview": {"phase": "completed"}},
        structured_output={"primary_diagnosis": "private diagnosis"},
    )
    db_session.add(session)
    await db_session.commit()

    url = f"/api/v1/agents/sessions/{session.id}/chat"
    anonymous = await client.post(url, json={"message": "tell me"})
    wrong_owner = await client.post(
        url, headers=_auth_header(other), json={"message": "tell me"}
    )

    assert anonymous.status_code == 404
    assert wrong_owner.status_code == 404
    children = await db_session.scalars(
        select(AgentSession).where(AgentSession.parent_session_id == session.id)
    )
    assert list(children) == []


@pytest.mark.asyncio
async def test_patient_can_recover_report_from_owned_case_after_local_cache_loss(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    patient = _patient("T3 Recovery Patient")
    db_session.add(patient)
    await db_session.flush()
    session = AgentSession(
        user_id=patient.id,
        session_type=AgentSessionType.DIAGNOSIS,
        structured_output={"primary_diagnosis": "example diagnosis"},
        context={"lab_reports": [{"file_id": "report-1", "indicators": []}]},
    )
    db_session.add(session)
    await db_session.flush()
    case = MedicalCase(
        patient_id=patient.id,
        source_session_id=session.id,
        title="Recovery case",
        status=CaseStatus.PENDING_REVIEW,
    )
    db_session.add(case)
    db_session.add(
        DocumentParseTask(
            file_id="report-1",
            filename="lab-report.txt",
            parse_method="file-extract",
            status="completed",
            file_bytes=b"lab data",
            result={"file_id": "report-1", "indicators": []},
            owner_user_id=patient.id,
            source_session_id=session.id,
            case_id=case.id,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/patient/cases/{case.id}/recovery",
        headers=_auth_header(patient),
    )

    assert response.status_code == 200
    assert response.json()["report"]["primary_diagnosis"] == "example diagnosis"
    assert response.json()["lab_reports"][0]["file_id"] == "report-1"


@pytest.mark.asyncio
async def test_case_material_download_requires_the_case_owner(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T3 Material Owner")
    other = _patient("T3 Material Other")
    db_session.add_all([owner, other])
    await db_session.flush()
    session = AgentSession(user_id=owner.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add(session)
    await db_session.flush()
    case = MedicalCase(
        patient_id=owner.id,
        source_session_id=session.id,
        title="Material case",
        status=CaseStatus.PENDING_REVIEW,
    )
    db_session.add(case)
    await db_session.flush()
    file_id = f"download-me-{uuid.uuid4()}"
    task = DocumentParseTask(
            file_id=file_id,
            filename="report.txt",
            parse_method="file-extract",
            status="completed",
            file_bytes=b"sensitive report bytes",
            result={"file_id": file_id, "indicators": []},
            owner_user_id=owner.id,
            source_session_id=session.id,
            case_id=case.id,
        )
    db_session.add(task)
    await db_session.commit()

    allowed = await client.get(
        f"/api/v1/patient/cases/{case.id}/materials/{task.file_id}",
        headers=_auth_header(owner),
    )
    denied = await client.get(
        f"/api/v1/patient/cases/{case.id}/materials/{task.file_id}",
        headers=_auth_header(other),
    )

    assert allowed.status_code == 200
    assert allowed.content == b"sensitive report bytes"
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_guest_uploads_move_to_user_and_cleanup_follows_guest_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = _patient("T3 Migrated Patient")
    guest = GuestSession(
        session_token=f"session-{uuid.uuid4()}",
        fingerprint="t3-test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add_all([owner, guest])
    await db_session.flush()
    guest_agent_session = AgentSession(
        guest_session_id=guest.id,
        session_type=AgentSessionType.DIAGNOSIS,
        structured_output={"primary_diagnosis": "guest diagnosis"},
        context={"_frontend_sid": "guest-client-session"},
    )
    db_session.add(guest_agent_session)
    await db_session.flush()
    task = DocumentParseTask(
        file_id=f"guest-file-{uuid.uuid4()}",
        filename="guest-report.txt",
        parse_method="file-extract",
        status="completed",
        file_bytes=b"guest bytes",
        result={"file_id": "guest-file", "indicators": []},
        owner_guest_id=guest.id,
        client_session_id="guest-client-session",
    )
    db_session.add(task)
    await db_session.commit()

    migrated = await client.post(
        "/api/v1/auth/guest/migrate",
        headers={
            **_auth_header(owner),
            "X-Guest-Token": create_guest_token(str(guest.id), "t3-test", platform="web"),
        },
    )
    await db_session.refresh(task)
    assert migrated.status_code == 200
    assert task.owner_user_id == owner.id
    assert task.owner_guest_id is None
    assert task.source_session_id == guest_agent_session.id
    recovered_case = await db_session.execute(
        select(MedicalCase).where(MedicalCase.source_session_id == guest_agent_session.id)
    )
    case = recovered_case.scalar_one()
    recovery = await client.get(
        f"/api/v1/patient/cases/{case.id}/recovery", headers=_auth_header(owner)
    )
    assert recovery.status_code == 200
    assert recovery.json()["report"]["primary_diagnosis"] == "guest diagnosis"
    assert recovery.json()["materials"][0]["file_id"] == task.file_id

    guest_two = GuestSession(
        session_token=f"session-{uuid.uuid4()}",
        fingerprint="t3-cleanup",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(guest_two)
    await db_session.flush()
    cleanup_task = DocumentParseTask(
        file_id=f"cleanup-file-{uuid.uuid4()}",
        filename="temporary.txt",
        parse_method="file-extract",
        status="processing",
        file_bytes=b"temporary",
        owner_guest_id=guest_two.id,
    )
    db_session.add(cleanup_task)
    await db_session.commit()

    cleaned = await client.delete(
        "/api/v1/auth/guest",
        headers={"X-Guest-Token": create_guest_token(str(guest_two.id), "t3-cleanup", platform="web")},
    )
    assert cleaned.status_code == 204
    remaining = await db_session.execute(
        select(DocumentParseTask).where(DocumentParseTask.file_id == cleanup_task.file_id)
    )
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_expired_database_guest_cannot_upload_or_read_saved_material(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    guest = GuestSession(
        session_token=f"session-{uuid.uuid4()}",
        fingerprint="expired-t3",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(guest)
    await db_session.flush()
    task = DocumentParseTask(
        file_id=f"expired-file-{uuid.uuid4()}",
        filename="expired.txt",
        parse_method="file-extract",
        status="completed",
        file_bytes=b"expired bytes",
        result={"file_id": "expired", "indicators": []},
        owner_guest_id=guest.id,
    )
    db_session.add(task)
    await db_session.commit()
    headers = {"X-Guest-Token": create_guest_token(str(guest.id), "expired-t3", platform="web")}

    result = await client.get(f"/api/v1/documents/{task.file_id}/result", headers=headers)
    uploaded = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("new.txt", b"data", "text/plain")},
    )

    assert result.status_code == 404
    assert uploaded.status_code == 401


@pytest.mark.asyncio
async def test_expired_guest_cleanup_removes_agent_sessions_and_original_files(
    db_session: AsyncSession,
) -> None:
    guest = GuestSession(
        session_token=f"session-{uuid.uuid4()}",
        fingerprint="expired-cleanup",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(guest)
    await db_session.flush()
    session = AgentSession(guest_session_id=guest.id, session_type=AgentSessionType.DIAGNOSIS)
    db_session.add(session)
    file_id = f"expired-cleanup-{uuid.uuid4()}"
    db_session.add(
        DocumentParseTask(
            file_id=file_id,
            filename="expired.txt",
            parse_method="file-extract",
            status="processing",
            file_bytes=b"expired original",
            owner_guest_id=guest.id,
        )
    )
    await db_session.commit()

    from app.tasks.documents import cleanup_expired_guest_sessions

    removed = await asyncio.to_thread(cleanup_expired_guest_sessions.run)

    assert removed >= 1
    remaining_sessions = await db_session.execute(
        select(AgentSession).where(AgentSession.id == session.id)
    )
    assert remaining_sessions.scalar_one_or_none() is None
    remaining = await db_session.execute(
        select(DocumentParseTask).where(DocumentParseTask.file_id == file_id)
    )
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_document_worker_persists_completed_result_and_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _patient("T3 Worker Patient")
    db_session.add(owner)
    await db_session.flush()
    successful = DocumentParseTask(
        file_id=f"worker-ok-{uuid.uuid4()}",
        filename="result.txt",
        parse_method="file-extract",
        status="queued",
        file_bytes=b"original bytes",
        owner_user_id=owner.id,
    )
    failed = DocumentParseTask(
        file_id=f"worker-failed-{uuid.uuid4()}",
        filename="broken.txt",
        parse_method="file-extract",
        status="queued",
        file_bytes=b"broken bytes",
        owner_user_id=owner.id,
    )
    db_session.add_all([successful, failed])
    await db_session.commit()

    from app.api.v1 import documents as document_api
    from app.tasks.documents import process_document_parse

    async def parse_ok(_db, file_bytes, _filename, file_id):
        assert file_bytes == b"original bytes"
        return {"file_id": file_id, "indicators": []}

    async def parse_fail(*_args):
        raise RuntimeError("parser unavailable")

    monkeypatch.setattr(document_api, "_parse_text_document", parse_ok)
    await asyncio.to_thread(process_document_parse.run, successful.file_id)
    monkeypatch.setattr(document_api, "_parse_text_document", parse_fail)
    await asyncio.to_thread(process_document_parse.run, failed.file_id)

    await db_session.refresh(successful)
    await db_session.refresh(failed)
    assert successful.status == "completed"
    assert successful.result == {"file_id": successful.file_id, "indicators": []}
    assert failed.status == "failed"
    assert failed.error == "parser unavailable"


@pytest.mark.asyncio
async def test_duplicate_worker_delivery_serializes_and_does_not_parse_twice(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if db_session.bind is None or db_session.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock behavior requires the task PostgreSQL database")

    owner = _patient("T3 Duplicate Worker Patient")
    db_session.add(owner)
    await db_session.flush()
    task = DocumentParseTask(
        file_id=f"worker-duplicate-{uuid.uuid4()}",
        filename="duplicate.txt",
        parse_method="file-extract",
        status="queued",
        file_bytes=b"once",
        owner_user_id=owner.id,
    )
    db_session.add(task)
    await db_session.commit()

    from app.api.v1 import documents as document_api
    from app.tasks.documents import _process_document_parse

    calls = 0

    async def parse_once(_db, _file_bytes, _filename, file_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return {"file_id": file_id, "indicators": []}

    monkeypatch.setattr(document_api, "_parse_text_document", parse_once)
    await asyncio.gather(
        _process_document_parse(task.file_id),
        _process_document_parse(task.file_id),
    )

    await db_session.refresh(task)
    assert calls == 1
    assert task.status == "completed"
