"""持久化患者上传文件与解析任务。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DocumentParseTask(Base):
    """保存上传文件、解析进度与其病例归属。"""

    __tablename__ = "document_parse_tasks"

    file_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parse_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    file_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    owner_guest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guest_sessions.id", ondelete="CASCADE"), nullable=True
    )
    client_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medical_cases.id", ondelete="CASCADE"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(owner_user_id IS NOT NULL AND owner_guest_id IS NULL) OR "
            "(owner_user_id IS NULL AND owner_guest_id IS NOT NULL)",
            name="ck_document_parse_exactly_one_owner",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_document_parse_status",
        ),
        Index("ix_document_parse_owner_user", "owner_user_id"),
        Index("ix_document_parse_owner_guest", "owner_guest_id"),
        Index("ix_document_parse_client_session", "client_session_id"),
        Index("ix_document_parse_source_session", "source_session_id"),
        Index("ix_document_parse_case", "case_id"),
        Index("ix_document_parse_user_client", "owner_user_id", "client_session_id"),
        Index("ix_document_parse_guest_client", "owner_guest_id", "client_session_id"),
    )
