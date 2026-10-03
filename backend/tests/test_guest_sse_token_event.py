import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
async def test_anonymous_route_stream_requires_a_precreated_guest_session():
    from app.api.v1 import agents as api
    from fastapi import HTTPException

    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    request = Request({"type": "http", "query_string": b"", "headers": []})
    context = SimpleNamespace(user=None, is_guest=False, platform="web", guest_id=None)

    with pytest.raises(HTTPException) as raised:
        await api.route_stream(
            req=api.RouteStreamRequest(message="合成患者主诉"),
            request=request,
            ctx=context,
            db=db,
        )

    assert raised.value.status_code == 401
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_guest_stream_works_without_issuing_another_token(monkeypatch):
    from app.api import deps
    from app.api.v1 import agents as api

    guest_id = uuid.UUID("a1295c7a-cc1d-42b4-b172-c2dfe7b1e034")
    guest = SimpleNamespace(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db = SimpleNamespace(get=AsyncMock(return_value=guest))
    guest_token = "synthetic-valid-guest-token"

    async def resolve_token(received_token, _db):
        assert received_token == guest_token
        return None, "web", True, str(guest_id)

    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    request = Request({
        "type": "http",
        "query_string": b"",
        "headers": [(b"x-guest-token", guest_token.encode())],
    })

    context = await deps.get_current_user_or_guest_lenient(
        request,
        token=None,
        x_guest_token=guest_token,
        db=SimpleNamespace(),
    )
    assert context.is_guest is True
    assert context.guest_id == str(guest_id)
    monkeypatch.setattr(api, "AgentOrchestrator", Mock())

    from fastapi.responses import StreamingResponse

    async def passthrough(_db, _ctx, *, event_generator, **_kwargs):
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    monkeypatch.setattr(api, "stream_guest_submission", passthrough)

    stream = await api.route_stream(
        req=api.RouteStreamRequest(message="合成患者主诉"),
        request=request,
        ctx=context,
        db=db,
    )
    try:
        event = await stream.body_iterator.__anext__()
    finally:
        await stream.body_iterator.aclose()

    assert event.startswith("event: thinking\n")
    assert "guest_token" not in event


@pytest.mark.parametrize(
    ("query_string", "expected_detail"),
    [
        (b"guest_token=synthetic-token", "请求头"),
        (b"message=synthetic-patient-text", "请求体"),
        (b"patient_history=synthetic-patient-text", "请求体"),
    ],
)
@pytest.mark.asyncio
async def test_route_stream_rejects_sensitive_query_values(
    monkeypatch, query_string, expected_detail
):
    from fastapi import HTTPException
    from app.api.v1 import agents as api

    request = Request({
        "type": "http",
        "query_string": query_string,
        "headers": [],
    })
    context = SimpleNamespace(
        user=SimpleNamespace(id="synthetic-user"),
        is_guest=False,
        platform="web",
        guest_id=None,
    )
    monkeypatch.setattr(api, "stream_guest_submission", AsyncMock())

    with pytest.raises(HTTPException) as raised:
        await api.route_stream(
            req=api.RouteStreamRequest(message="合成患者主诉"),
            request=request,
            ctx=context,
            db=SimpleNamespace(),
        )

    assert raised.value.status_code == 400
    assert expected_detail in raised.value.detail


@pytest.mark.parametrize(
    "query_string",
    [
        b"token=synthetic-token",
        b"guest_token=synthetic-token",
        b"access_token=synthetic-token",
        b"message=synthetic-patient-text",
        b"patient_history=synthetic-patient-text",
        b"answer=synthetic-patient-text",
    ],
)
@pytest.mark.asyncio
async def test_patient_sse_auth_dependency_rejects_sensitive_query_before_token_resolution(
    monkeypatch, query_string
):
    from fastapi import HTTPException
    from app.api import deps

    resolve_token = AsyncMock()
    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    request = Request({
        "type": "http",
        "query_string": query_string,
        "headers": [],
    })

    with pytest.raises(HTTPException) as raised:
        await deps.get_current_user_or_guest_lenient_no_query(
            request,
            token=None,
            x_guest_token=None,
            db=SimpleNamespace(),
        )

    assert raised.value.status_code == 400
    resolve_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_patient_sse_auth_dependency_keeps_header_guest_authentication(monkeypatch):
    from app.api import deps

    guest_token = "synthetic-header-guest-token"

    async def resolve_token(received_token, _db):
        assert received_token == guest_token
        return None, "web", True, "synthetic-guest-id"

    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    request = Request({
        "type": "http",
        "query_string": b"session_id=synthetic-session",
        "headers": [(b"x-guest-token", guest_token.encode())],
    })

    context = await deps.get_current_user_or_guest_lenient_no_query(
        request,
        token=None,
        x_guest_token=guest_token,
        db=SimpleNamespace(),
    )

    assert context.is_guest is True
    assert context.guest_id == "synthetic-guest-id"


@pytest.mark.parametrize("transport", ["bearer", "cookie"])
@pytest.mark.asyncio
async def test_patient_sse_auth_dependency_keeps_bearer_and_cookie_authentication(
    monkeypatch, transport
):
    from app.api import deps

    auth_token = f"synthetic-{transport}-token"
    user = SimpleNamespace(id="synthetic-user-id")

    async def resolve_token(received_token, _db):
        assert received_token == auth_token
        return user, "web", False, None

    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    headers = []
    token = None
    if transport == "bearer":
        headers.append((b"authorization", f"Bearer {auth_token}".encode()))
        token = auth_token
    else:
        headers.append((b"cookie", f"auth_token={auth_token}".encode()))
    request = Request({
        "type": "http",
        "query_string": b"session_id=synthetic-session",
        "headers": headers,
    })

    context = await deps.get_current_user_or_guest_lenient_no_query(
        request,
        token=token,
        x_guest_token=None,
        db=SimpleNamespace(),
    )

    assert context.user is user
    assert context.platform == "web"
    assert context.is_guest is False


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/agents/route/stream", {"message": "合成主诉"}),
        (
            "/api/v1/agents/route/stream/continue?session_id=synthetic-session"
            "&question_id=demo_duration",
            {"answer": "合成回答"},
        ),
        (
            "/api/v1/agents/sessions/synthetic-session/chat",
            {"message": "合成追问"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_patient_sse_routes_reject_query_auth_before_resolving_token(
    monkeypatch, path, body
):
    from httpx import ASGITransport, AsyncClient
    from app.api import deps
    from app.db.session import get_db
    from app.main import app

    resolve_token = AsyncMock()
    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    original_overrides = app.dependency_overrides.copy()

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            separator = "&" if "?" in path else "?"
            response = await client.post(
                f"{path}{separator}guest_token=synthetic-url-token", json=body
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert response.status_code == 400
    assert "请求头" in response.json()["detail"]
    resolve_token.assert_not_awaited()


@pytest.mark.parametrize("transport", ["query", "header"])
@pytest.mark.asyncio
async def test_invalid_guest_token_is_rejected_instead_of_creating_a_new_guest(
    monkeypatch, transport
):
    from fastapi import HTTPException
    from app.api import deps

    guest_token = "synthetic-expired-guest-token"

    async def resolve_expired_token(_token, _db):
        return None, "unknown", False, None

    monkeypatch.setattr(deps, "_resolve_token", resolve_expired_token)
    if transport == "query":
        request = Request({
            "type": "http",
            "query_string": f"guest_token={guest_token}".encode(),
            "headers": [],
        })
        header_token = None
    else:
        request = Request({
            "type": "http",
            "query_string": b"",
            "headers": [(b"x-guest-token", guest_token.encode())],
        })
        header_token = guest_token

    with pytest.raises(HTTPException) as raised:
        await deps.get_current_user_or_guest_lenient(
            request,
            token=None,
            x_guest_token=header_token,
            db=SimpleNamespace(),
        )

    assert raised.value.status_code == 401
    assert raised.value.detail == "Token is invalid or expired"
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize("transport", ["query", "header"])
@pytest.mark.asyncio
async def test_guest_token_resolution_database_failure_is_not_hidden(monkeypatch, transport):
    from app.api import deps

    guest_token = "synthetic-guest-token"

    async def fail_resolution(_token, _db):
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(deps, "_resolve_token", fail_resolution)
    if transport == "query":
        request = Request({
            "type": "http",
            "query_string": f"guest_token={guest_token}".encode(),
            "headers": [],
        })
        header_token = None
    else:
        request = Request({
            "type": "http",
            "query_string": b"",
            "headers": [(b"x-guest-token", guest_token.encode())],
        })
        header_token = guest_token

    with pytest.raises(RuntimeError, match="synthetic database outage"):
        await deps.get_current_user_or_guest_lenient(
            request,
            token=None,
            x_guest_token=header_token,
            db=SimpleNamespace(),
        )


@pytest.mark.parametrize("transport", ["query", "authorization"])
@pytest.mark.asyncio
async def test_invalid_registered_user_token_is_not_downgraded_to_guest(monkeypatch, transport):
    from fastapi import HTTPException
    from app.api import deps

    access_token = "synthetic-expired-access-token"

    async def resolve_expired_token(_token, _db):
        return None, "unknown", False, None

    monkeypatch.setattr(deps, "_resolve_token", resolve_expired_token)
    if transport == "query":
        request = Request({
            "type": "http",
            "query_string": f"token={access_token}".encode(),
            "headers": [],
        })
        bearer_token = None
    else:
        request = Request({
            "type": "http",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {access_token}".encode())],
        })
        bearer_token = access_token

    with pytest.raises(HTTPException) as raised:
        await deps.get_current_user_or_guest_lenient(
            request,
            token=bearer_token,
            x_guest_token=None,
            db=SimpleNamespace(),
        )

    assert raised.value.status_code == 401
    assert raised.value.detail == "Token is invalid or expired"
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_anonymous_sse_request_still_receives_an_empty_context():
    from app.api import deps

    request = Request({"type": "http", "query_string": b"", "headers": []})
    context = await deps.get_current_user_or_guest_lenient(
        request,
        token=None,
        x_guest_token=None,
        db=SimpleNamespace(),
    )

    assert context.user is None
    assert context.is_guest is False
    assert context.guest_id is None


@pytest.mark.parametrize(
    ("query_string", "cookie", "bearer_token", "header_guest", "expected_token"),
    [
        (b"token=user-query&guest_token=guest-query", None, "user-bearer", "guest-header", "user-bearer"),
        (b"token=user-query&guest_token=guest-query", None, None, "guest-header", "guest-header"),
        (b"token=user-query&guest_token=guest-query", None, None, None, "user-query"),
        (b"guest_token=guest-query", "auth_token=user-cookie", None, None, "guest-query"),
        (b"", "auth_token=user-cookie", None, None, "user-cookie"),
    ],
)
@pytest.mark.asyncio
async def test_sse_authentication_uses_documented_credential_priority(
    monkeypatch, query_string, cookie, bearer_token, header_guest, expected_token
):
    from app.api import deps

    user = SimpleNamespace(id="synthetic-user")
    received_tokens = []

    async def resolve_token(received_token, _db):
        received_tokens.append(received_token)
        if received_token.startswith("user-"):
            return user, "web", False, None
        return None, "web", True, str(uuid.UUID("a1295c7a-cc1d-42b4-b172-c2dfe7b1e034"))

    monkeypatch.setattr(deps, "_resolve_token", resolve_token)
    headers = []
    if bearer_token:
        headers.append((b"authorization", f"Bearer {bearer_token}".encode()))
    if header_guest:
        headers.append((b"x-guest-token", header_guest.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    request = Request({"type": "http", "query_string": query_string, "headers": headers})

    context = await deps.get_current_user_or_guest_lenient(
        request,
        token=bearer_token,
        x_guest_token=header_guest,
        db=SimpleNamespace(),
    )

    assert received_tokens == [expected_token]
    if expected_token.startswith("user-"):
        assert context.user is user
        assert context.is_guest is False
    else:
        assert context.is_guest is True


@pytest.mark.parametrize("subject", [None, "not-a-uuid"])
@pytest.mark.asyncio
async def test_guest_jwt_without_uuid_subject_is_not_authenticated(monkeypatch, subject):
    from app.api import deps

    class Redis:
        async def get(self, _key):
            return None

    monkeypatch.setattr(deps, "get_redis", lambda: Redis())
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _token: {"type": "guest", "sub": subject},
    )

    resolved = await deps._resolve_token("synthetic-signed-guest-token", SimpleNamespace())

    assert resolved == (None, "unknown", False, None)


@pytest.mark.parametrize("subject", [None, "not-a-uuid", 123])
@pytest.mark.asyncio
async def test_access_jwt_without_uuid_subject_is_not_authenticated(monkeypatch, subject):
    from app.api import deps

    class Redis:
        async def get(self, _key):
            return None

    monkeypatch.setattr(deps, "get_redis", lambda: Redis())
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _token: {"type": "access", "sub": subject},
    )

    resolved = await deps._resolve_token("synthetic-signed-access-token", SimpleNamespace())

    assert resolved == (None, "unknown", False, None)


@pytest.mark.asyncio
async def test_access_jwt_with_valid_uuid_subject_resolves_active_user(monkeypatch):
    from app.api import deps

    class Redis:
        async def get(self, _key):
            return None

    user_id = uuid.UUID("280fb1a6-3f3c-4e1f-8fda-7a15337b1838")
    user = SimpleNamespace(id=user_id, status="active")
    result = SimpleNamespace(scalar_one_or_none=lambda: user)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(deps, "get_redis", lambda: Redis())
    monkeypatch.setattr(
        deps,
        "decode_token",
        lambda _token: {"type": "access", "sub": str(user_id), "platform": "web"},
    )

    resolved = await deps._resolve_token("synthetic-signed-access-token", db)

    assert resolved == (user, "web", False, None)
    db.execute.assert_awaited_once()
