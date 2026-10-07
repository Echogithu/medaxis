"""归档字段不承载 AI 同意或医生核验声明。"""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    category: Literal['lab', 'imaging', 'other'] = 'other'
    institution: str = Field(default='', max_length=200)
    examination_date: date | None = None
    report_date: date | None = None
    notes: str = Field(default='', max_length=4000)

    @field_validator('examination_date', 'report_date', mode='before')
    @classmethod
    def date_only(cls, value):
        if value is not None and not isinstance(value, date) and (not isinstance(value, str) or len(value) != 10):
            raise ValueError('日期需使用 YYYY-MM-DD，不填写时请留空')
        return value


class ReportUpload(ReportFields):
    request_id: UUID
    ownership_declared: Literal[True]
    duplicate_mode: Literal['ask', 'separate', 'reuse'] = 'ask'
    duplicate_report_id: UUID | None = None

    @model_validator(mode='after')
    def duplicate_choice(self):
        if (self.duplicate_mode == 'reuse') != (self.duplicate_report_id is not None):
            raise ValueError('复用需明确选择已有报告；另存不携带复用编号')
        return self

    @field_validator('ownership_declared', mode='before')
    @classmethod
    def explicit_ownership(cls, value):
        if value is not True:
            raise ValueError('请明确确认归档的是本人报告')
        return value


class ReportEdit(ReportFields):
    expected_revision: int = Field(ge=0, strict=True)


class ReportPageText(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page: int = Field(ge=1, le=20, strict=True)
    text: str = Field(max_length=60000)


class ReportWorkflowVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_source_version: int = Field(ge=1, strict=True)
    expected_workflow_revision: int = Field(ge=0, strict=True)


class ReportExtractRequest(ReportWorkflowVersion):
    request_id: UUID


class ReportPreviewRequest(ReportWorkflowVersion):
    pages: list[ReportPageText] | None = Field(default=None, min_length=1, max_length=20)


class ReportAIRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    preview_id: UUID
    preview_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_source_version: int = Field(ge=1, strict=True)
    consent: Literal[True]
    ownership_confirmed: Literal[True]

    @field_validator('consent', 'ownership_confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('请逐次明确确认脱敏文本外发及本人归属')
        return value
