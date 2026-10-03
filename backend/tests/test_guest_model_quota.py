"""访客模型请求服务端配额与提交幂等 API 回归测试。"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import deps
from app.api.deps import UserContext
from app.db.session import get_db
from app.main import app
from app.api.v1 import agents
from app.db import redis_client
from app.core.security import create_guest_token
from app.models.agent import AgentSession, AgentSessionStatus, AgentSessionType
from app.models.config import SystemSetting
from app.models.guest_submission import GuestModelSubmission
from app.models.user import GuestSession
from app.services import guest_model_quota
from app.services.guest_model_quota import (
    GuestSubmissionReservation,
    reserve_guest_submission,
    stream_guest_submission,
)


@pytest.fixture(autouse=True)
def _disable_token_blacklist_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RedisWithoutRevokedTokens:
        async def get(self, _key: str) -> None:
            return None

        async def exists(self, _key: str) -> bool:
            return False

        async def set(self, *_args: object, **_kwargs: object) -> bool:
            return True

    monkeypatch.setattr(deps, "get_redis", _RedisWithoutRevokedTokens)
    monkeypatch.setattr(redis_client, "get_redis", _RedisWithoutRevokedTokens)


async def _create_guest(db_session: AsyncSession, *, max_messages: int) -> tuple[GuestSession, str]:
    guest = GuestSession(
        session_token=f"quota-{uuid.uuid4()}",
        fingerprint="synthetic-quota-test",
        max_messages=max_messages,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(guest)
    await db_session.commit()
    return guest, create_guest_token(str(guest.id), platform="web")


@pytest.mark.asyncio
async def test_guest_creation_uses_the_admin_configured_model_quota(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        SystemSetting(
            key="auth.guest_max_messages",
            value="2",
            description="synthetic quota test",
            category="auth",
            value_type="number",
        )
    )
    await db_session.commit()

    response = await client.post("/api/v1/auth/guest", headers={"X-Platform": "web"})

    assert response.status_code == 201
    assert response.json()["max_messages"] == 2


@pytest.mark.asyncio
async def test_continue_stream_is_post_only_and_does_not_accept_answer_from_query(
    client: AsyncClient,
) -> None:
    url = "/api/v1/agents/route/stream/continue"
    params = {
        "session_id": str(uuid.uuid4()),
        "question_id": "synthetic-question",
        "answer": "synthetic answer must not be accepted from URL",
    }

    legacy_get = await client.get(url, params=params)
    query_answer_post = await client.post(url, params=params, json={"answer": "合成请求体回答"})

    assert legacy_get.status_code == 405
    assert query_answer_post.status_code == 400


@pytest.mark.parametrize(
    ("path", "payload", "agent_name", "method_name"),
    [
        ("/api/v1/agents/route", {"message": "合成问诊消息"}, "AgentOrchestrator", "route"),
        ("/api/v1/agents/diagnose", {"symptoms": "合成症状描述足够长"}, "DiagnosisAgent", "analyze"),
        ("/api/v1/agents/plan", {"diagnosis": "合成诊断结果"}, "PlanningAgent", "plan"),
        ("/api/v1/agents/monitor", {"patient_updates": "合成病情进展"}, "MonitoringAgent", "check"),
        ("/api/v1/agents/consult", {"symptoms": "合成症状描述足够长"}, "AgentOrchestrator", "route"),
    ],
)
@pytest.mark.asyncio
async def test_nonstream_guest_model_submission_replay_is_idempotent_and_charged_once(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, str],
    agent_name: str,
    method_name: str,
) -> None:
    guest, token = await _create_guest(db_session, max_messages=1)
    submission_id = str(uuid.uuid4())
    call_count = 0

    async def _stub_model(_self: object, **_kwargs: object) -> SimpleNamespace | dict[str, str]:
        nonlocal call_count
        call_count += 1
        if agent_name == "AgentOrchestrator":
            return {"stub": "synthetic model response"}
        if agent_name == "DiagnosisAgent":
            return SimpleNamespace(
                structured_output=None,
                content="合成治疗建议",
                tool_calls_used=[],
                session_id=None,
            )
        return SimpleNamespace(structured_output=None, content="合成治疗建议")

    monkeypatch.setattr(getattr(agents, agent_name), method_name, _stub_model)
    headers = {
        "X-Guest-Token": token,
        "Idempotency-Key": submission_id,
    }
    first = await client.post(path, headers=headers, json=payload)
    replay = await client.post(path, headers=headers, json=payload)
    field_to_change = next(iter(payload))
    mismatched_replay = await client.post(
        path,
        headers=headers,
        json={field_to_change: f"{payload[field_to_change]} changed"},
    )
    exhausted = await client.post(
        path,
        headers={"X-Guest-Token": token, "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )
    missing_key = await client.post(path, headers={"X-Guest-Token": token}, json=payload)
    status = await client.get(
        "/api/v1/auth/guest/status",
        headers={"X-Guest-Token": token},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert mismatched_replay.status_code == 409
    assert exhausted.status_code == 429
    assert missing_key.status_code == 400
    assert call_count == 1
    assert status.json()["interaction_count"] == 1
    assert status.json()["remaining"] == 0
    assert await db_session.get(GuestSession, guest.id) is not None


@pytest.mark.asyncio
async def test_streaming_model_error_refunds_and_replays_error_events(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    guest, token = await _create_guest(db_session, max_messages=1)
    submission_id = str(uuid.uuid4())
    event_calls = 0
    ctx = UserContext(user=None, platform="web", is_guest=True, guest_id=str(guest.id))

    async def _model_error_event():
        nonlocal event_calls
        event_calls += 1
        yield 'event: error\ndata: {"code":"PROVIDER_UNAVAILABLE"}\n\n'

    async def _submit():
        return await stream_guest_submission(
            db_session,
            ctx,
            submission_id=submission_id,
            endpoint="agents.route.stream",
            request_payload={"message": "合成问诊"},
            event_generator=_model_error_event,
        )

    failed = await _submit()
    failed_iterator = failed.body_iterator
    failed_event = await failed_iterator.__anext__()
    assert failed_event.startswith("event: error")
    row = await db_session.scalar(
        select(GuestModelSubmission).where(
            GuestModelSubmission.guest_session_id == guest.id,
            GuestModelSubmission.submission_id == submission_id,
        )
    )
    assert row is not None
    assert row.status == "failed"
    assert row.quota_refunded is True
    await failed_iterator.aclose()

    replay = await _submit()
    replay_body = "".join([chunk async for chunk in replay.body_iterator])
    status = await client.get(
        "/api/v1/auth/guest/status",
        headers={"X-Guest-Token": token},
    )

    assert failed_event == replay_body
    assert '"code":"PROVIDER_UNAVAILABLE"' in failed_event
    assert event_calls == 1
    assert status.json()["interaction_count"] == 0
    assert row.status == "failed"
    assert row.quota_refunded is True


@pytest.mark.asyncio
async def test_stream_success_is_committed_before_complete_event_is_exposed(
    db_session: AsyncSession,
) -> None:
    guest, _token = await _create_guest(db_session, max_messages=1)
    submission_id = str(uuid.uuid4())
    ctx = UserContext(user=None, platform="web", is_guest=True, guest_id=str(guest.id))

    async def _successful_events():
        yield 'event: thinking\ndata: {}\n\n'
        yield 'event: complete\ndata: {"status":"done"}\n\n'

    response = await stream_guest_submission(
        db_session,
        ctx,
        submission_id=submission_id,
        endpoint="agents.route.stream",
        request_payload={"message": "合成问诊"},
        event_generator=_successful_events,
    )
    iterator = response.body_iterator

    first = await iterator.__anext__()
    assert first.startswith("event: thinking")
    complete = await iterator.__anext__()
    assert complete.startswith("event: complete")

    row = await db_session.scalar(
        select(GuestModelSubmission).where(
            GuestModelSubmission.guest_session_id == guest.id,
            GuestModelSubmission.submission_id == submission_id,
        )
    )
    assert row is not None
    assert row.status == "succeeded"
    assert row.quota_refunded is False

    # 客户端收到 complete 后立即断开，不能把已完成请求改成失败并返还额度。
    await iterator.aclose()
    await db_session.refresh(guest)
    assert guest.message_count == 1


@pytest.mark.asyncio
async def test_failed_guest_model_submission_refunds_once_and_same_key_replays_failure(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guest, token = await _create_guest(db_session, max_messages=1)
    failed_submission_id = str(uuid.uuid4())
    call_count = 0

    async def _stub_plan(_self: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HTTPException(status_code=503, detail="synthetic provider failure")
        return SimpleNamespace(structured_output=None, content="合成重试成功")

    monkeypatch.setattr(agents.PlanningAgent, "plan", _stub_plan)
    failed_headers = {
        "X-Guest-Token": token,
        "Idempotency-Key": failed_submission_id,
    }
    payload = {"diagnosis": "合成诊断结果"}

    failed = await client.post("/api/v1/agents/plan", headers=failed_headers, json=payload)
    failed_replay = await client.post(
        "/api/v1/agents/plan", headers=failed_headers, json=payload
    )
    status_after_failure = await client.get(
        "/api/v1/auth/guest/status",
        headers={"X-Guest-Token": token},
    )
    retried_as_new_submission = await client.post(
        "/api/v1/agents/plan",
        headers={"X-Guest-Token": token, "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )

    assert failed.status_code == 503
    assert failed_replay.status_code == 503
    assert failed_replay.json() == failed.json()
    assert status_after_failure.json()["interaction_count"] == 0
    assert retried_as_new_submission.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_concurrent_guest_submissions_cannot_spend_the_last_quota_twice(
    client: AsyncClient,
    db_session: AsyncSession,
    test_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _guest, token = await _create_guest(db_session, max_messages=1)
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _independent_db_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _independent_db_session
    model_started = asyncio.Event()
    release_model = asyncio.Event()
    model_calls = 0

    async def _stub_route(_self: object, **_kwargs: object) -> dict[str, str]:
        nonlocal model_calls
        model_calls += 1
        model_started.set()
        await release_model.wait()
        return {"stub": "synthetic model response"}

    monkeypatch.setattr(agents.AgentOrchestrator, "route", _stub_route)
    common_headers = {"X-Guest-Token": token}
    first_task = asyncio.create_task(
        client.post(
            "/api/v1/agents/route",
            headers={**common_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"message": "合成首个提交"},
        )
    )
    try:
        await asyncio.wait_for(model_started.wait(), timeout=5)
        second = await client.post(
            "/api/v1/agents/route",
            headers={**common_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"message": "合成并发提交"},
        )
    finally:
        release_model.set()
    first = await first_task
    status = await client.get("/api/v1/auth/guest/status", headers=common_headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert model_calls == 1
    assert status.json()["interaction_count"] == 1


@pytest.mark.asyncio
async def test_stale_pending_submission_refunds_quota_and_replays_terminal_failure(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest, token = await _create_guest(db_session, max_messages=1)
    submission_id = str(uuid.uuid4())
    payload = agents.RouteRequest(message="合成服务中断恢复").model_dump(mode="json")
    ctx = UserContext(user=None, platform="web", is_guest=True, guest_id=str(guest.id))
    reservation = await reserve_guest_submission(
        db_session,
        ctx,
        submission_id=submission_id,
        endpoint="agents.route",
        request_payload=payload,
    )
    assert reservation is not None and reservation.created
    row = await db_session.get(GuestModelSubmission, reservation.id)
    assert row is not None
    row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    await db_session.commit()

    model_calls = 0

    async def _stub_route(_self: object, **_kwargs: object) -> dict[str, str]:
        nonlocal model_calls
        model_calls += 1
        return {"stub": "must not execute for stale replay"}

    monkeypatch.setattr(agents.AgentOrchestrator, "route", _stub_route)
    headers = {"X-Guest-Token": token, "Idempotency-Key": submission_id}
    first = await client.post("/api/v1/agents/route", headers=headers, json={"message": payload["message"]})
    replay = await client.post("/api/v1/agents/route", headers=headers, json={"message": payload["message"]})
    status = await client.get("/api/v1/auth/guest/status", headers={"X-Guest-Token": token})
    finalized = await db_session.get(GuestModelSubmission, reservation.id)

    assert first.status_code == replay.status_code == 503
    assert first.json() == replay.json()
    assert model_calls == 0
    assert status.json()["interaction_count"] == 0
    assert finalized is not None
    assert finalized.status == "failed"
    assert finalized.quota_refunded is True


@pytest.mark.asyncio
async def test_new_submission_recovers_another_stale_pending_reservation(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest, token = await _create_guest(db_session, max_messages=1)
    old_submission_id = str(uuid.uuid4())
    old_ctx = UserContext(user=None, platform="web", is_guest=True, guest_id=str(guest.id))
    old_reservation = await reserve_guest_submission(
        db_session,
        old_ctx,
        submission_id=old_submission_id,
        endpoint="agents.route",
        request_payload={"message": "合成旧请求"},
    )
    assert old_reservation is not None and old_reservation.created
    old_row = await db_session.get(GuestModelSubmission, old_reservation.id)
    assert old_row is not None
    old_row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    await db_session.commit()

    model_calls = 0

    async def _stub_route(_self: object, **_kwargs: object) -> dict[str, str]:
        nonlocal model_calls
        model_calls += 1
        return {"stub": "synthetic response"}

    monkeypatch.setattr(agents.AgentOrchestrator, "route", _stub_route)
    new_submission_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/agents/route",
        headers={"X-Guest-Token": token, "Idempotency-Key": new_submission_id},
        json={"message": "合成新请求"},
    )
    status = await client.get("/api/v1/auth/guest/status", headers={"X-Guest-Token": token})
    await db_session.refresh(old_row)

    assert response.status_code == 200
    assert model_calls == 1
    assert status.json()["interaction_count"] == 1
    assert old_row.status == "failed"
    assert old_row.quota_refunded is True


@pytest.mark.asyncio
async def test_failure_finalization_database_error_is_not_silenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_to_persist(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(guest_model_quota, "_finish_guest_submission", _fail_to_persist)
    reservation = GuestSubmissionReservation(
        id=uuid.uuid4(),
        guest_session_id=uuid.uuid4(),
        created=True,
    )

    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        await guest_model_quota._finish_after_failure(
            SimpleNamespace(),
            reservation,
            status_code=500,
            payload={"detail": "synthetic"},
        )


@pytest.mark.asyncio
async def test_failure_finalization_error_surfaces_when_stream_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish_started = asyncio.Event()

    async def _fail_to_persist(*_args: object, **_kwargs: object) -> None:
        finish_started.set()
        await asyncio.sleep(0)
        raise RuntimeError("synthetic cancelled persistence failure")

    monkeypatch.setattr(guest_model_quota, "_finish_guest_submission", _fail_to_persist)
    reservation = GuestSubmissionReservation(
        id=uuid.uuid4(),
        guest_session_id=uuid.uuid4(),
        created=True,
    )
    finalizer = asyncio.create_task(
        guest_model_quota._finish_after_failure(
            SimpleNamespace(),
            reservation,
            status_code=500,
            payload={"detail": "synthetic"},
        )
    )
    await finish_started.wait()
    finalizer.cancel()

    with pytest.raises(RuntimeError, match="synthetic cancelled persistence failure"):
        await finalizer


@pytest.mark.asyncio
async def test_streaming_guest_routes_share_quota_and_replay_without_duplicate_work(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest, token = await _create_guest(db_session, max_messages=3)
    pending_session_id = uuid.uuid4()
    completed_session_id = uuid.uuid4()
    db_session.add_all(
        [
            AgentSession(
                id=pending_session_id,
                guest_session_id=guest.id,
                session_type=AgentSessionType.DIAGNOSIS,
                status=AgentSessionStatus.ACTIVE,
                context={"interview": {"phase": "interviewing"}},
            ),
            AgentSession(
                id=completed_session_id,
                guest_session_id=guest.id,
                session_type=AgentSessionType.DIAGNOSIS,
                status=AgentSessionStatus.COMPLETED,
                context={"interview": {"phase": "completed"}},
                structured_output={"primary_diagnosis": "synthetic diagnosis"},
            ),
        ]
    )
    await db_session.commit()

    model_calls = {"classify": 0, "first_stream": 0, "continue": 0, "chat": 0}

    async def _classify(_message: str, *, session_context: object = None) -> dict[str, str]:
        model_calls["classify"] += 1
        return {"intent": "general", "confidence": "high", "reasoning": "synthetic"}

    class _StubOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            self.master = SimpleNamespace(classify_intent=_classify)

    class _StubLLMService:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def chat_stream(self, **_kwargs: object):
            model_calls["first_stream"] += 1
            yield "合成首问回答"

        async def chat(self, **_kwargs: object) -> SimpleNamespace:
            model_calls["chat"] += 1
            return SimpleNamespace(content="合成诊后回答")

    question = SimpleNamespace(
        question_id="synthetic-question",
        question="合成追问",
        type="text",
        options=[],
        hint=None,
        allow_skip=False,
        phase="interviewing",
        colloquial_phase=None,
    )
    state = SimpleNamespace(
        is_sufficient=False,
        red_flags_detected=[],
        asked_questions=["synthetic-question"],
        phase="interviewing",
    )

    async def _interview_answer(
        _self: object, **_kwargs: object
    ) -> tuple[list[SimpleNamespace], SimpleNamespace, list[object], str, str]:
        model_calls["continue"] += 1
        return [question], state, [], "continue", "synthetic"

    async def _build_chat_context(
        _db: AsyncSession, _parent: AgentSession, *, user_id: str | None
    ) -> str:
        return "synthetic diagnosis context"

    monkeypatch.setattr(agents, "AgentOrchestrator", _StubOrchestrator)
    monkeypatch.setattr(agents, "LLMService", _StubLLMService)
    monkeypatch.setattr(agents.DiagnosisAgent, "interview_answer", _interview_answer)
    monkeypatch.setattr(agents, "_build_chat_context", _build_chat_context)
    auth = {"X-Guest-Token": token}

    first_key = str(uuid.uuid4())
    first_headers = {**auth, "Idempotency-Key": first_key}
    first_payload = {"message": "合成首问", "patient_history": "既往合成病史"}
    first = await client.post(
        "/api/v1/agents/route/stream", headers=first_headers, json=first_payload
    )
    first_replay = await client.post(
        "/api/v1/agents/route/stream", headers=first_headers, json=first_payload
    )

    continue_key = str(uuid.uuid4())
    continue_headers = {**auth, "Idempotency-Key": continue_key}
    continue_url = (
        f"/api/v1/agents/route/stream/continue?session_id={pending_session_id}"
        "&question_id=synthetic-question"
    )
    continued = await client.post(
        continue_url,
        headers=continue_headers,
        json={"answer": "合成回答"},
    )
    continued_replay = await client.post(
        continue_url,
        headers=continue_headers,
        json={"answer": "合成回答"},
    )

    chat_key = str(uuid.uuid4())
    chat_headers = {**auth, "Idempotency-Key": chat_key}
    chat_url = f"/api/v1/agents/sessions/{completed_session_id}/chat"
    chatted = await client.post(chat_url, headers=chat_headers, json={"message": "合成追问"})
    chatted_replay = await client.post(
        chat_url,
        headers=chat_headers,
        json={"message": "合成追问"},
    )
    status = await client.get("/api/v1/auth/guest/status", headers=auth)

    assert first.status_code == first_replay.status_code == 200
    assert first_replay.text == first.text
    assert continued.status_code == continued_replay.status_code == 200
    assert continued_replay.text == continued.text
    assert chatted.status_code == chatted_replay.status_code == 200
    assert chatted_replay.text == chatted.text
    assert model_calls == {"classify": 1, "first_stream": 1, "continue": 1, "chat": 1}
    assert status.json()["interaction_count"] == 3

    cached_submissions = (
        await db_session.scalars(
            select(GuestModelSubmission).where(
                GuestModelSubmission.guest_session_id == guest.id
            )
        )
    ).all()
    assert len(cached_submissions) == 3
    assert all(row.status == "succeeded" for row in cached_submissions)
    assert all(token not in json.dumps(row.response_payload) for row in cached_submissions)
    child_count = await db_session.scalar(
        select(func.count()).select_from(AgentSession).where(
            AgentSession.parent_session_id == completed_session_id
        )
    )
    assert child_count == 1
