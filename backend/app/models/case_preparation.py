"""患者就医准备的不可变来源快照与患者核对状态。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CasePreparationPackage(Base):
    __tablename__ = "case_preparation_packages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medical_cases.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    package: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="ready_for_review")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_case_preparation_case_version"),
        UniqueConstraint("case_id", "source_fingerprint", name="uq_case_preparation_source"),
        CheckConstraint("version > 0", name="ck_case_preparation_version_positive"),
        CheckConstraint("revision > 0", name="ck_case_preparation_revision_positive"),
        CheckConstraint(
            "state IN ('ready_for_review', 'needs_reassessment')",
            name="ck_case_preparation_state",
        ),
    )
