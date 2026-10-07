"""管理操作绑定患者已看到的状态，彻底删除要求单独明确确认。"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_state_token: str = Field(pattern=r'^[0-9a-f]{64}$')


class ReportPurgeRequest(ReportLifecycleRequest):
    confirmed_permanent_delete: Literal[True]

    @field_validator('confirmed_permanent_delete', mode='before')
    @classmethod
    def explicit_delete(cls, value):
        if value is not True:
            raise ValueError('彻底删除须明确确认')
        return value
