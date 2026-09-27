"""访客数据迁移端点的双身份与原子性回归测试。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.security import create_access_token, create_guest_token
from app.main import app
from app.models.agent import AgentSession
from app.models.user import GuestSession, User, UserRole, UserStatus


def _new_user(label: str) -> User:
    return User(
        email=f"{label}-{uuid.uuid4()}@example.com",
        hashed_password="unused-in-this-test",
        full_name=label,
        role=UserRole.PATIENT,
        status=UserStatus.ACTIVE,
    )


async def _create_guest_with_sessions(
    db_session: AsyncSession, *, expires_at: datetime | None = None, count: int = 2
) -> tuple[GuestSession, list[AgentSession]]:
    guest = GuestSession(
        session_token=str(uuid.uuid4()),
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db_session.add(guest)
    await db_session.flush()
    sessions = [
        AgentSession(guest_session_id=guest.id, context={"messages": []})
        for _ in range(count)
    ]
    db_session.add_all(sessions)
    await db_session.commit()
    return guest, sessions


def _migration_headers(user: User, guest_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}",
        "X-Guest-Token": create_guest_token(str(guest_id), platform="web"),
    }


@pytest.mark.asyncio
async def test_migrates_guest_sessions_when_both_identities_are_supplied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("migration-owner")
    db_session.add(user)
    await db_session.flush()
    guest, sessions = await _create_guest_with_sessions(db_session)
    session_ids = [item.id for item in sessions]
    guest_id = guest.id

    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers=_migration_headers(user, guest_id),
    )

    assert response.status_code == 200
    assert response.json() == {"migrated": len(sessions)}
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id.in_(session_ids))
    )
    migrated = result.scalars().all()
    assert all(item.user_id == user.id for item in migrated)
    assert all(item.guest_session_id is None for item in migrated)


@pytest.mark.asyncio
async def test_rejects_guest_token_when_database_session_is_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("expired-migration-owner")
    db_session.add(user)
    await db_session.flush()
    guest, sessions = await _create_guest_with_sessions(
        db_session, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers=_migration_headers(user, guest.id),
    )

    assert response.status_code == 410
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id.in_([item.id for item in sessions]))
    )
    assert all(item.guest_session_id == guest.id for item in result.scalars().all())


@pytest.mark.asyncio
async def test_rejects_malformed_guest_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("invalid-migration-owner")
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers={
            "Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}",
            "X-Guest-Token": "not-a-valid-jwt",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_expired_guest_jwt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("expired-jwt-owner")
    guest, _ = await _create_guest_with_sessions(db_session, count=1)
    db_session.add(user)
    await db_session.commit()
    expired_token = jwt.encode(
        {
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "sub": str(guest.id),
            "type": "guest",
        },
        get_settings().secret_key.get_secret_value(),
        algorithm="HS256",
    )

    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers={
            "Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}",
            "X-Guest-Token": expired_token,
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_migration_without_both_identity_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("missing-token-owner")
    db_session.add(user)
    await db_session.commit()

    missing_user = await client.post(
        "/api/v1/auth/guest/migrate",
        headers={"X-Guest-Token": create_guest_token(str(uuid.uuid4()))},
    )
    missing_guest = await client.post(
        "/api/v1/auth/guest/migrate",
        headers={
            "Authorization": f"Bearer {create_access_token(str(user.id), platform='web')}"
        },
    )

    assert missing_user.status_code == 400
    assert missing_guest.status_code == 401


@pytest.mark.asyncio
async def test_repeat_migration_is_idempotent_for_same_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = _new_user("repeat-migration-owner")
    db_session.add(user)
    await db_session.flush()
    guest, sessions = await _create_guest_with_sessions(db_session, count=1)
    headers = _migration_headers(user, guest.id)

    first = await client.post("/api/v1/auth/guest/migrate", headers=headers)
    second = await client.post("/api/v1/auth/guest/migrate", headers=headers)

    assert first.status_code == 200
    assert first.json() == {"migrated": 1}
    assert second.status_code == 200
    assert second.json() == {"migrated": 0}
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id == sessions[0].id)
    )
    migrated = result.scalar_one()
    assert migrated.user_id == user.id
    assert migrated.guest_session_id is None


@pytest.mark.asyncio
async def test_conflicting_user_ownership_is_rejected_without_reassignment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    existing_owner = _new_user("existing-session-owner")
    requested_owner = _new_user("requested-session-owner")
    db_session.add_all([existing_owner, requested_owner])
    await db_session.flush()
    guest, sessions = await _create_guest_with_sessions(db_session, count=1)
    session_id = sessions[0].id
    guest_id = guest.id
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    session = result.scalar_one()
    session.user_id = existing_owner.id
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers=_migration_headers(requested_owner, guest_id),
    )

    assert response.status_code == 409
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id == session_id)
    )
    unchanged = result.scalar_one()
    assert unchanged.user_id == existing_owner.id
    assert unchanged.guest_session_id == guest_id


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_all_guest_session_changes(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _new_user("failed-migration-owner")
    db_session.add(user)
    await db_session.flush()
    guest, sessions = await _create_guest_with_sessions(db_session)
    guest_id = guest.id
    session_ids = [item.id for item in sessions]

    async def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    response = await client.post(
        "/api/v1/auth/guest/migrate",
        headers=_migration_headers(user, guest.id),
    )

    assert response.status_code == 500
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id.in_(session_ids))
    )
    unchanged = result.scalars().all()
    assert all(item.user_id is None for item in unchanged)
    assert all(item.guest_session_id == guest_id for item in unchanged)


@pytest.mark.asyncio
async def test_concurrent_migration_to_two_users_transfers_to_only_one(
    db_session: AsyncSession,
    test_engine,
) -> None:
    if not test_engine.url.drivername.startswith("postgresql"):
        pytest.skip("row-lock concurrency contract requires PostgreSQL")

    first_user = _new_user("race-owner-one")
    second_user = _new_user("race-owner-two")
    db_session.add_all([first_user, second_user])
    await db_session.flush()
    user_ids = {first_user.id, second_user.id}
    guest, sessions = await _create_guest_with_sessions(db_session, count=2)
    guest_id = guest.id
    session_ids = [item.id for item in sessions]
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    headers = [
        _migration_headers(first_user, guest_id),
        _migration_headers(second_user, guest_id),
    ]
    try:
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first_client,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as second_client,
        ):
            first_response, second_response = await asyncio.gather(
                first_client.post("/api/v1/auth/guest/migrate", headers=headers[0]),
                second_client.post("/api/v1/auth/guest/migrate", headers=headers[1]),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert first_response.status_code == second_response.status_code == 200
    assert first_response.json()["migrated"] + second_response.json()["migrated"] == len(sessions)
    db_session.expire_all()
    result = await db_session.execute(
        select(AgentSession).where(AgentSession.id.in_(session_ids))
    )
    migrated = result.scalars().all()
    assert len({item.user_id for item in migrated}) == 1
    assert migrated[0].user_id in user_ids
    assert all(item.guest_session_id is None for item in migrated)
