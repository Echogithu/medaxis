"""病例选择独立于医生授权；更新来源必须逐项明确指定。"""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SaveReportLinks(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_links_revision: int = Field(ge=0, strict=True)
    expected_review_revision: int = Field(ge=0, strict=True)
    expected_source_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    case_ids: list[UUID] = Field(max_length=50)
    refresh_case_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator('case_ids', 'refresh_case_ids')
    @classmethod
    def distinct(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('病例选择不能重复')
        return sorted(values, key=str)

    @model_validator(mode='after')
    def selected_refresh(self):
        if not set(self.refresh_case_ids).issubset(self.case_ids):
            raise ValueError('更新来源的病例必须包含在保留的关联中')
        return self
