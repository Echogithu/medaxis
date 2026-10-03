"""患者授权的定向咨询与不可覆盖的医患留言。"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

ACTIVE_STATES = ('pending', 'accepted', 'awaiting_patient')
TERMINAL_STATES = ('completed', 'declined', 'cancelled', 'unavailable')


def now():
    return datetime.now(timezone.utc)


class Consultation(Base):
    __tablename__ = 'consultations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('medical_cases.id', ondelete='CASCADE'), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    doctor_profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='pending')
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        CheckConstraint("state IN ('pending','accepted','awaiting_patient','completed','declined','cancelled','unavailable')", name='ck_consultation_state'),
        CheckConstraint('revision > 0', name='ck_consultation_revision'),
        Index('uq_consultation_active_case', 'case_id', unique=True, postgresql_where=text("state IN ('pending','accepted','awaiting_patient')")),
        Index('ix_consultation_patient_updated', 'patient_id', 'updated_at'),
        Index('ix_consultation_doctor_updated', 'doctor_id', 'updated_at'),
    )


class ConsultationMessage(Base):
    __tablename__ = 'consultation_messages'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    consultation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('consultations.id', ondelete='CASCADE'), nullable=False, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    author_profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))
    next_state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
