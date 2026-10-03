"""患者手动随访：每项任务代表一次复查或自测，不猜测周期与医嘱。"""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CareTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: UUID | None = None
    type: Literal["follow_up", "self_check"] = "follow_up"
    description: str = Field(min_length=1, max_length=500)
    due_date: date
    unit: str = Field(default="", max_length=30)


class CarePlanFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    source_case_id: UUID | None = None
    start_date: date
    end_date: date
    tasks: list[CareTaskInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dates_and_ids(self):
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        if any(not self.start_date <= task.due_date <= self.end_date for task in self.tasks):
            raise ValueError("任务日期必须在计划起止日期内")
        ids = [task.id for task in self.tasks if task.id]
        if len(ids) != len(set(ids)):
            raise ValueError("任务 ID 不能重复")
        return self


class CarePlanCreate(CarePlanFields):
    request_id: UUID


class CarePlanEdit(CarePlanFields):
    expected_revision: int = Field(ge=0)


class CarePlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm", "pause", "resume", "cancel"]
    expected_revision: int = Field(ge=0)


class CheckInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan_id: UUID
    task_id: str = Field(min_length=1, max_length=100)
    value: float | None = Field(default=None, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("value", mode="before")
    @classmethod
    def reject_bool_value(cls, value):
        if isinstance(value, bool):
            raise ValueError("数值不能使用布尔值")
        return value
