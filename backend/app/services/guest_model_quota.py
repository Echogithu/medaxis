"""访客模型提交的原子配额、幂等回放与失败退款。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import UserContext
from app.core.config import get_settings
from app.models.guest_submission import GuestModelSubmission
from app.models.user import GuestSession

logger = logging.getLogger("guest.model_quota")
_STALE_PENDING_AFTER = timedelta(minutes=15)
_STREAMING_ENDPOINTS = frozenset(
    {
        "agents.route.stream",
        "agents.route.stream.continue",
        "agents.sessions.chat",
    }
)


@dataclass(frozen=True)
class GuestSubmissionReservation:
    id: uuid.UUID
    guest_session_id: uuid.UUID
    created: bool
    response_status: int | None = None
    response_payload: dict[str, Any] | list[Any] | None = None


def _payload_hash(endpoint: str, payload: Any) -> str:
    canonical = json.dumps(
        {"endpoint": endpoint, "payload": jsonable_encoder(payload)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_submission_id(value: str | None) -> str:
    if not value:
        raise HTTPException(
            status_code=400,
            detail="访客模型请求必须提供 Idempotency-Key。",
        )
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key 必须是 UUID。",
        ) from exc


async def _recover_stale_guest_submissions(
    db: AsyncSession,
    guest: GuestSession,
    *,
    now: datetime,
) -> bool:
    """在访客下一次提交时归还超时 pending 的额度，避免不同键也被旧请求卡住。"""
    stale_rows = (
        await db.scalars(
            select(GuestModelSubmission)
            .where(
                GuestModelSubmission.guest_session_id == guest.id,
                GuestModelSubmission.status == "pending",
                GuestModelSubmission.updated_at <= now - _STALE_PENDING_AFTER,
            )
            .with_for_update()
        )
    ).all()
    if not stale_rows:
        return False

    message = "请求中断时间过长，本次额度已返还，请重新发起提交。"
    for row in stale_rows:
        if not row.quota_refunded:
            guest.message_count = max(0, guest.message_count - 1)
            row.quota_refunded = True
        row.status = "failed"
        row.response_status = 503
        if row.endpoint in _STREAMING_ENDPOINTS:
            payload: dict[str, Any] = {
                "events": [_sse_error_event("SUBMISSION_INTERRUPTED", message)]
            }
        else:
            payload = {"detail": message}
        row.response_payload = jsonable_encoder(payload)
        row.updated_at = now
    await db.commit()
    return True


async def reserve_guest_submission(
    db: AsyncSession,
    ctx: UserContext,
    *,
    submission_id: str | None,
    endpoint: str,
    request_payload: Any,
) -> GuestSubmissionReservation | None:
    """锁定访客计数行，在同一事务内扣一次并记录幂等键。"""
    if not ctx.is_guest:
        return None
    if not ctx.guest_id:
        raise HTTPException(status_code=401, detail="访客身份无效。")

    normalized_id = _normalize_submission_id(submission_id)
    try:
        guest_id = uuid.UUID(ctx.guest_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="访客身份无效。") from exc

    guest = await db.scalar(
        select(GuestSession)
        .where(GuestSession.id == guest_id)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if guest is None or guest.expires_at <= now:
        raise HTTPException(status_code=401, detail="访客会话已过期。")

    if await _recover_stale_guest_submissions(db, guest, now=now):
        guest = await db.scalar(
            select(GuestSession)
            .where(GuestSession.id == guest_id)
            .with_for_update()
        )
        now = datetime.now(timezone.utc)
        if guest is None or guest.expires_at <= now:
            raise HTTPException(status_code=401, detail="访客会话已过期。")

    row = await db.scalar(
        select(GuestModelSubmission)
        .where(
            GuestModelSubmission.guest_session_id == guest_id,
            GuestModelSubmission.submission_id == normalized_id,
        )
        .with_for_update()
    )
    request_hash = _payload_hash(endpoint, request_payload)
    if row is not None:
        if row.endpoint != endpoint or not hmac.compare_digest(row.request_hash, request_hash):
            raise HTTPException(
                status_code=409,
                detail="同一 Idempotency-Key 不能用于不同的提交内容。",
            )
        if row.status == "pending":
            updated_at = row.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if now - updated_at > _STALE_PENDING_AFTER:
                message = "请求中断时间过长，本次额度已返还，请重新发起提交。"
                if endpoint in _STREAMING_ENDPOINTS:
                    response_payload: dict[str, Any] = {
                        "events": [_sse_error_event("SUBMISSION_INTERRUPTED", message)]
                    }
                else:
                    response_payload = {"detail": message}
                stale_reservation = GuestSubmissionReservation(
                    id=row.id,
                    guest_session_id=guest_id,
                    created=True,
                )
                await _finish_guest_submission(
                    db,
                    stale_reservation,
                    status="failed",
                    response_status=503,
                    response_payload=response_payload,
                    refund=True,
                )
                return GuestSubmissionReservation(
                    id=row.id,
                    guest_session_id=guest_id,
                    created=False,
                    response_status=503,
                    response_payload=response_payload,
                )
            raise HTTPException(
                status_code=409,
                detail="该提交仍在处理中，请稍后使用相同 Idempotency-Key 重试。",
                headers={"Retry-After": "1"},
            )
        return GuestSubmissionReservation(
            id=row.id,
            guest_session_id=guest_id,
            created=False,
            response_status=row.response_status or 200,
            response_payload=row.response_payload,
        )

    if guest.message_count >= guest.max_messages:
        raise HTTPException(
            status_code=429,
            detail="访客可用问诊次数已用完。",
            headers={"Retry-After": "3600"},
        )

    guest.message_count += 1
    row = GuestModelSubmission(
        guest_session_id=guest_id,
        submission_id=normalized_id,
        endpoint=endpoint,
        request_hash=request_hash,
        status="pending",
        quota_refunded=False,
    )
    db.add(row)
    await db.commit()
    return GuestSubmissionReservation(
        id=row.id,
        guest_session_id=guest_id,
        created=True,
    )


async def _finish_guest_submission(
    db: AsyncSession,
    reservation: GuestSubmissionReservation,
    *,
    status: str,
    response_status: int,
    response_payload: Any,
    refund: bool,
) -> None:
    guest = await db.scalar(
        select(GuestSession)
        .where(GuestSession.id == reservation.guest_session_id)
        .with_for_update()
    )
    row = await db.scalar(
        select(GuestModelSubmission)
        .where(GuestModelSubmission.id == reservation.id)
        .with_for_update()
    )
    if row is None or row.status != "pending":
        return

    if refund and guest is not None and not row.quota_refunded:
        guest.message_count = max(0, guest.message_count - 1)
        row.quota_refunded = True

    row.status = status
    row.response_status = response_status
    row.response_payload = jsonable_encoder(response_payload)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def _finish_after_failure(
    db: AsyncSession,
    reservation: GuestSubmissionReservation,
    *,
    status_code: int,
    payload: Any,
) -> None:
    finish_task = asyncio.create_task(
        _finish_guest_submission(
            db,
            reservation,
            status="failed",
            response_status=status_code,
            response_payload=payload,
            refund=True,
        )
    )
    try:
        await asyncio.shield(finish_task)
    except asyncio.CancelledError:
        try:
            await finish_task
        except BaseException:
            logger.exception("Could not finalize failed guest submission after cancellation")
            raise
        raise
    except Exception:
        logger.exception("Could not finalize failed guest submission")
        raise


async def run_guest_submission(
    db: AsyncSession,
    ctx: UserContext,
    *,
    submission_id: str | None,
    endpoint: str,
    request_payload: Any,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    """执行一个 REST 模型提交；重复成功返回原响应，失败退款且固定失败结果。"""
    reservation = await reserve_guest_submission(
        db,
        ctx,
        submission_id=submission_id,
        endpoint=endpoint,
        request_payload=request_payload,
    )
    if reservation is None:
        return await operation()
    if not reservation.created:
        return JSONResponse(
            status_code=reservation.response_status or 200,
            content=reservation.response_payload or {},
        )

    try:
        result = await operation()
    except HTTPException as exc:
        await _finish_after_failure(
            db,
            reservation,
            status_code=exc.status_code,
            payload={"detail": jsonable_encoder(exc.detail)},
        )
        raise
    except BaseException:
        await _finish_after_failure(
            db,
            reservation,
            status_code=500,
            payload={"detail": "模型请求失败，请保留内容后重试。"},
        )
        raise

    await _finish_guest_submission(
        db,
        reservation,
        status="succeeded",
        response_status=200,
        response_payload=result,
        refund=False,
    )
    return result


def _sse_error_event(code: str, message: str) -> str:
    return f"event: error\ndata: {json.dumps({'code': code, 'error': message}, ensure_ascii=False)}\n\n"


def _submission_error_event(exc: HTTPException) -> str:
    if exc.status_code == 429:
        return _sse_error_event("GUEST_QUOTA_EXHAUSTED", str(exc.detail))
    if exc.status_code == 409:
        return _sse_error_event("IDEMPOTENCY_CONFLICT", str(exc.detail))
    return _sse_error_event("IDEMPOTENCY_KEY_INVALID", str(exc.detail))


async def _yield_cached_events(events: list[str]) -> AsyncIterator[str]:
    for event in events:
        yield event


async def stream_guest_submission(
    db: AsyncSession,
    ctx: UserContext,
    *,
    submission_id: str | None,
    endpoint: str,
    request_payload: Any,
    event_generator: Callable[[], AsyncIterator[str]],
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """为 SSE 访客提交预扣、缓存成功事件并在失败或断线时退款。"""
    try:
        reservation = await reserve_guest_submission(
            db,
            ctx,
            submission_id=submission_id,
            endpoint=endpoint,
            request_payload=request_payload,
        )
    except HTTPException as exc:
        if exc.status_code not in (400, 409, 429):
            raise
        return StreamingResponse(
            _yield_cached_events([_submission_error_event(exc)]),
            media_type="text/event-stream",
            headers=headers,
        )

    if reservation is not None and not reservation.created:
        payload = reservation.response_payload
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list) or not events:
            events = [_sse_error_event("SUBMISSION_FAILED", "本次请求已失败，请重新提交。")]
        return StreamingResponse(
            _yield_cached_events([event for event in events if isinstance(event, str)]),
            media_type="text/event-stream",
            headers=headers,
        )

    async def _quota_event_generator() -> AsyncIterator[str]:
        if reservation is None:
            async for event in event_generator():
                yield event
            return

        cached_events: list[str] = []
        saw_complete = False
        saw_error = False
        finalized = False
        try:
            async for event in event_generator():
                # 访客令牌属于凭证，任何重放缓存都不得持有它。
                if not event.startswith("event: guest_token\n"):
                    cached_events.append(event)
                if event.startswith("event: complete\n"):
                    saw_complete = True
                    await _finish_guest_submission(
                        db,
                        reservation,
                        status="succeeded",
                        response_status=200,
                        response_payload={"events": cached_events},
                        refund=False,
                    )
                    finalized = True
                elif event.startswith("event: error\n"):
                    saw_error = True
                    await _finish_after_failure(
                        db,
                        reservation,
                        status_code=200,
                        payload={"events": cached_events},
                    )
                    finalized = True
                yield event
        except BaseException:
            if not finalized:
                await _finish_after_failure(
                    db,
                    reservation,
                    status_code=500,
                    payload={
                        "events": [
                            _sse_error_event(
                                "SUBMISSION_INTERRUPTED",
                                "连接中断或服务失败；本次额度已返还。",
                            )
                        ]
                    },
                )
            raise

        if not finalized and (saw_error or not saw_complete):
            if not saw_error:
                cached_events.append(
                    _sse_error_event(
                        "SUBMISSION_INTERRUPTED",
                        "服务未能完成本次请求；本次额度已返还。",
                    )
                )
            await _finish_after_failure(
                db,
                reservation,
                status_code=200,
                payload={"events": cached_events},
            )
        elif not finalized:
            await _finish_guest_submission(
                db,
                reservation,
                status="succeeded",
                response_status=200,
                response_payload={"events": cached_events},
                refund=False,
            )

    return StreamingResponse(
        _quota_event_generator(),
        media_type="text/event-stream",
        headers=headers or {
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
