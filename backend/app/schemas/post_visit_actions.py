"""诊后AI只整理已有记录；生效必须由患者确认具体安排。"""
from datetime import date, time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class FollowUpSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=1000)
    type: Literal["follow_up", "self_check"] = "follow_up"
    due_date: date | None = None


class MedicationSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    dosage: str = Field(default="", max_length=100)
    evidence: str = Field(min_length=1, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None
    times: list[str] = Field(default_factory=list, max_length=6)


class ExtractedActions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    follow_ups: list[FollowUpSuggestion] = Field(default_factory=list, max_length=20)
    medications: list[MedicationSuggestion] = Field(default_factory=list, max_length=5)


class GenerateActions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: int = Field(ge=1)
    preview_hash: str = Field(min_length=64, max_length=64)
    consent: Literal[True]

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("本次模型处理需要明确同意")
        return value


class FollowUpConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    due_date: date


class MedicationConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    times: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def schedule_valid(self):
        if self.end_date < self.start_date or (self.end_date-self.start_date).days > 90:
            raise ValueError("用药提醒日期区间必须有效，单次最多91天")
        if len(self.times) != len(set(self.times)):
            raise ValueError("提醒时刻不能重复")
        for item in self.times:
            parsed = time.fromisoformat(item)
            if parsed.tzinfo or parsed.second or parsed.microsecond or len(item) != 5:
                raise ValueError("提醒时刻使用北京时间HH:mm")
        return self


class ConfirmActions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
    source_revision: int = Field(ge=1)
    follow_ups: list[FollowUpConfirmation] = Field(default_factory=list, max_length=20)
    medications: list[MedicationConfirmation] = Field(default_factory=list, max_length=5)
    channel: Literal["in_app", "email"] = "in_app"


class DismissActions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100)
