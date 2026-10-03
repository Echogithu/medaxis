"""患者病例列表和按 ID 恢复的轻量 API 契约。"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.patient import get_case_recovery, list_cases
from app.models.user import UserRole


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.value)


class _Session:
    def __init__(self, result):
        self.result = result
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.result)


@pytest.mark.asyncio
async def test_case_list_supports_bounded_page_and_deterministic_order() -> None:
    db = _Session([])

    await list_cases(SimpleNamespace(id=uuid.uuid4()), page=2, limit=10, db=db)

    statement = db.statements[0]
    assert statement._offset_clause.value == 10
    assert statement._limit_clause.value == 10
    assert len(statement._where_criteria) == 1
    assert len(statement._order_by_clauses) == 2


@pytest.mark.asyncio
async def test_case_recovery_is_a_direct_owner_scoped_lookup() -> None:
    patient_id = uuid.uuid4()
    case_id = uuid.uuid4()
    db = _Session(None)

    with pytest.raises(HTTPException) as caught:
        await get_case_recovery(
            case_id,
            SimpleNamespace(id=patient_id, role=UserRole.PATIENT),
            db,
        )

    assert caught.value.status_code == 404
    statement = db.statements[0]
    assert len(statement._where_criteria) == 2
    assert "medical_cases.id" in str(statement)
    assert "medical_cases.patient_id" in str(statement)
