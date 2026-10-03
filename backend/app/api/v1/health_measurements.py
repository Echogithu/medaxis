"""本人指标记录：追加保存、重复请求去重、分页历史。"""
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentUser
from app.db.session import get_db
from app.models.health_measurement import HealthMeasurement
from app.models.user import User, UserRole

router = APIRouter()


class MeasurementInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    systolic: int | None = Field(default=None, ge=40, le=300, strict=True)
    diastolic: int | None = Field(default=None, ge=20, le=200, strict=True)
    heart_rate: int | None = Field(default=None, ge=20, le=250, strict=True)
    weight: float | None = Field(default=None, ge=2, le=500, allow_inf_nan=False, strict=True)
    recorded_at: AwareDatetime

    @model_validator(mode='after')
    def check_readings(self):
        if (self.systolic is None) != (self.diastolic is None):
            raise ValueError('血压需同时填写收缩压与舒张压')
        if self.systolic is not None and self.systolic <= self.diastolic:
            raise ValueError('收缩压应大于舒张压，请核对读数')
        if all(value is None for value in (self.systolic, self.heart_rate, self.weight)):
            raise ValueError('请至少填写一项健康指标')
        if self.recorded_at > datetime.now(timezone.utc):
            raise ValueError('记录时间不能晚于当前时间')
        return self


def patient_only(user):
    if user.role != UserRole.PATIENT:
        raise HTTPException(403, '仅患者可维护本人健康指标')


def serialize(item):
    return {field: str(item.id) if field == 'id' else getattr(item, field) for field in
            ('id', 'systolic', 'diastolic', 'heart_rate', 'weight', 'recorded_at', 'created_at')} | {'source': 'patient_reported'}


@router.get('/measurements')
async def list_measurements(user: CurrentUser, db: AsyncSession = Depends(get_db),
                            page: Annotated[int, Query(ge=1)] = 1, limit: Annotated[int, Query(ge=1, le=50)] = 10):
    patient_only(user)
    items = (await db.scalars(select(HealthMeasurement).where(HealthMeasurement.patient_id == user.id)
        .order_by(HealthMeasurement.recorded_at.desc(), HealthMeasurement.id.desc()).offset((page - 1) * limit).limit(limit + 1))).all()
    return {'items': [serialize(item) for item in items[:limit]], 'has_more': len(items) > limit}


@router.post('/measurements', status_code=201)
async def create_measurement(data: MeasurementInput, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    patient_only(user)
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    fields = data.model_dump(exclude={'request_id'})
    existing = await db.get(HealthMeasurement, data.request_id)
    if existing:
        if existing.patient_id != user.id or any(getattr(existing, key) != value for key, value in fields.items()):
            raise HTTPException(409, '记录请求已使用，请重新核对并提交')
        return serialize(existing)
    item = HealthMeasurement(id=data.request_id, patient_id=user.id, **fields)
    db.add(item)
    await db.commit()
    return serialize(item)
