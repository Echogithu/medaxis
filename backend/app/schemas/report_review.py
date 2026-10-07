"""草稿可未填完；确认必须核对已保存的精确版本，不携带替换正文。"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source_page: int | None = Field(default=None, ge=1, le=20, strict=True)
    evidence: str | None = Field(default=None, max_length=4000)

    @field_validator('evidence', mode='before')
    @classmethod
    def empty_evidence(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ReviewIndicator(ReviewItem):
    name: str = Field(default='', max_length=200)
    raw_value: str = Field(default='', max_length=200)
    unit: str | None = Field(default=None, max_length=100)
    reference_range: str | None = Field(default=None, max_length=300)
    abnormal_mark: str | None = Field(default=None, max_length=100)

    @field_validator('unit', 'reference_range', 'abnormal_mark', mode='before')
    @classmethod
    def empty_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ReviewSection(ReviewItem):
    kind: Literal['findings', 'conclusion', 'other'] = 'other'
    text: str = Field(default='', max_length=4000)


class ReviewContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    indicators: list[ReviewIndicator] = Field(default_factory=list, max_length=100)
    sections: list[ReviewSection] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def total_text(self):
        characters = sum(len(value) for item in [*self.indicators, *self.sections]
            for value in item.model_dump().values() if isinstance(value, str))
        if characters > 60000:
            raise ValueError('核对文字合计不能超过60000字')
        return self


class ReviewWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    expected_source_epoch: int = Field(ge=0, strict=True)
    expected_source_version: int = Field(ge=1, strict=True)
    expected_source_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class SaveReviewDraft(ReviewWrite):
    content: ReviewContent
    based_on_version_id: UUID | None = None
    candidate_job_id: UUID | None = None

    @model_validator(mode='after')
    def one_origin(self):
        if self.based_on_version_id and self.candidate_job_id:
            raise ValueError('请明确采用草稿历史或AI候选的一种来源')
        return self


class ConfirmReview(ReviewWrite):
    draft_id: UUID
    checked_against_original: Literal[True]

    @field_validator('checked_against_original', mode='before')
    @classmethod
    def explicit_check(cls, value):
        if value is not True:
            raise ValueError('请单独确认已对照原件')
        return value
