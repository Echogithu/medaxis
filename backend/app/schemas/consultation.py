"""咨询请求使用业务提交 ID 和版本防止重复与陈旧写入。"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class ConsultationCreate(BaseModel):
    request_id: UUID
    case_id: UUID
    doctor_id: UUID
    source_fingerprint: str = Field(min_length=64, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    material_ids: list[str] = Field(default_factory=list, max_length=10)
    share_confirmed: Literal[True]

    @field_validator('question')
    @classmethod
    def question_not_blank(cls, value):
        if not value.strip():
            raise ValueError('请填写咨询问题')
        return value.strip()


class ConsultationAction(BaseModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    action: Literal['accept', 'decline', 'cancel', 'end']
    reason: str = Field(default='', max_length=1000)


class ConsultationReply(BaseModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=5000)
    category: Literal['report_explanation', 'health_advice', 'visit_advice', 'request_information'] | None = None
    next_state: Literal['awaiting_patient', 'completed'] | None = None

    @field_validator('body')
    @classmethod
    def body_not_blank(cls, value):
        if not value.strip():
            raise ValueError('请填写留言内容')
        return value.strip()
