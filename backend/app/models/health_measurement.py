"""患者自报指标历史，与档案基础资料独立保存。"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class HealthMeasurement(Base):
    __tablename__ = 'patient_health_measurements'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    systolic: Mapped[int | None] = mapped_column(Integer)
    diastolic: Mapped[int | None] = mapped_column(Integer)
    heart_rate: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (
        CheckConstraint('(systolic IS NULL AND diastolic IS NULL) OR (systolic IS NOT NULL AND diastolic IS NOT NULL AND systolic > diastolic AND systolic BETWEEN 40 AND 300 AND diastolic BETWEEN 20 AND 200)', name='ck_measurement_pressure'),
        CheckConstraint('heart_rate IS NULL OR heart_rate BETWEEN 20 AND 250', name='ck_measurement_heart_rate'),
        CheckConstraint('weight IS NULL OR weight BETWEEN 2 AND 500', name='ck_measurement_weight'),
        CheckConstraint('systolic IS NOT NULL OR heart_rate IS NOT NULL OR weight IS NOT NULL', name='ck_measurement_content'),
        Index('ix_measurement_patient_recorded', 'patient_id', 'recorded_at', 'id'),
    )
