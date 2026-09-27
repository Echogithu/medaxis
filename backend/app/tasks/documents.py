"""Celery task for persistent medical document parsing."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.db.session import AsyncSessionLocal, async_engine
from app.models.document_parse import DocumentParseTask
from app.models.agent import AgentSession
from app.models.user import GuestSession
from app.services.document_router import ParseMethod
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_in_fresh_event_loop(coroutine) -> int | None:
    async def run_and_dispose_pool():
        try:
            return await coroutine
        finally:
            await async_engine.dispose()

    return asyncio.run(run_and_dispose_pool())


@celery_app.task(
    bind=True,
    name="app.tasks.documents.process_document_parse",
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_document_parse(self, file_id: str) -> None:
    """Parse one persisted upload; a repeated task updates the same row."""
    _run_in_fresh_event_loop(_process_document_parse(file_id))


@celery_app.task(name="app.tasks.documents.cleanup_expired_guest_sessions")
def cleanup_expired_guest_sessions() -> int:
    """按访客期限删除访客会话、问诊会话和原始上传文件。"""
    return _run_in_fresh_event_loop(_cleanup_expired_guest_sessions()) or 0


async def _cleanup_expired_guest_sessions() -> int:
    async with AsyncSessionLocal() as db:
        expired_result = await db.execute(
            select(GuestSession.id).where(
                GuestSession.expires_at <= datetime.now(timezone.utc)
            )
        )
        expired_ids = list(expired_result.scalars().all())
        if not expired_ids:
            return 0
        await db.execute(
            delete(AgentSession).where(AgentSession.guest_session_id.in_(expired_ids))
        )
        deleted = await db.execute(
            delete(GuestSession).where(GuestSession.id.in_(expired_ids))
        )
        await db.commit()
        return deleted.rowcount or 0


async def _process_document_parse(file_id: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(DocumentParseTask)
            .where(DocumentParseTask.file_id == file_id)
            .with_for_update()
        )
        if task is None or task.status in {"completed", "failed"}:
            return
        filename = task.filename
        file_bytes = task.file_bytes
        method = task.parse_method
        task.status = "processing"
        task.error = None

        try:
            # Import lazily so API and worker share the parser without a module cycle.
            from app.api.v1.documents import _parse_image, _parse_text_document

            if method == ParseMethod.IMAGE_VISION.value:
                result = await _parse_image(db, file_bytes, file_id)
            elif method == ParseMethod.FILE_EXTRACT.value:
                result = await _parse_text_document(db, file_bytes, filename, file_id)
            else:
                raise ValueError(f"Unsupported parse method: {method}")

            task.status = "completed"
            task.result = result
            task.error = None
            await db.commit()
        except Exception as exc:
            await db.rollback()
            # Re-read under a row lock so a delayed failure can never replace
            # a result committed by another delivery.
            current = await db.scalar(
                select(DocumentParseTask)
                .where(DocumentParseTask.file_id == file_id)
                .with_for_update()
            )
            if current is not None and current.status != "completed":
                current.status = "failed"
                current.error = str(exc)[:4000]
                await db.commit()
            logger.exception("Document parse failed for file_id=%s", file_id)
