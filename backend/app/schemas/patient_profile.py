"""患者填报档案的输入契约，来源和更新时间由服务器维护。"""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RecordState = Literal["present", "none", "unknown", "not_recorded"]


class DiseaseRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: UUID | None = None
    code: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=100)
    category: Literal["chronic", "special"] = "chronic"
    severity: Literal["unknown", "mild", "moderate", "severe"] = "unknown"
    diagnosed_date: date | None = None
    notes: str = Field(default="", max_length=1000)

    @field_validator("diagnosed_date")
    @classmethod
    def reject_future_diagnosis(cls, value):
        if value and value > datetime.now(timezone(timedelta(hours=8))).date():
            raise ValueError("确诊日期不能晚于今天")
        return value


class MedicationRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    dosage: str = Field(default="", max_length=100)
    frequency: str = Field(default="", max_length=100)
    start_date: date | None = None
    status: Literal["active", "stopped"] = "active"


class SectionStates(BaseModel):
    allergies: RecordState | None = None
    conditions: RecordState | None = None
    medications: RecordState | None = None


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, pattern=r"^(male|female|男|女)$")
    height: int | None = Field(default=None, ge=50, le=300)
    weight: int | None = Field(default=None, ge=10, le=500)
    allergies: list[str] | None = Field(default=None, max_length=50)
    chronic_diseases: list[DiseaseRecord] | None = Field(default=None, max_length=20)
    medications: list[MedicationRecord] | None = Field(default=None, max_length=20)
    section_states: SectionStates | None = None
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def validate_supplied_name(cls, value):
        if value is None or not str(value).strip():
            raise ValueError("姓名不能为空")
        return str(value).strip()

    @field_validator("gender", mode="before")
    @classmethod
    def empty_gender_is_unknown(cls, value):
        return None if value == "" else value

    @field_validator("allergies")
    @classmethod
    def validate_allergies(cls, value):
        if value is None:
            return None
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 100 for item in cleaned):
            raise ValueError("过敏记录不能为空，且每项最多100字")
        return list(dict.fromkeys(cleaned))
