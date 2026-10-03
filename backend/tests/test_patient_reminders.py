"""患者提醒路由的状态与分页契约。"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from uuid import UUID

from app.api.v1.patient import acknowledge_reminder, list_reminders


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
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.result)

    async def commit(self):
        self.commits += 1


def _event(status: str, acknowledged_at=None):
    return SimpleNamespace(
        id="reminder-1",
        patient_id="patient-1",
        event_type="medication",
        payload={"name": "合成药物"},
        scheduled_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
        triggered_at=None,
        acknowledged_at=acknowledged_at,
        status=status,
        plan_id=None,
        retry_count=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "in_flight", "failed", "cancelled"])
async def test_reminder_cannot_be_acknowledged_before_delivery(status: str) -> None:
    event = _event(status)
    db = _Session(event)

    with pytest.raises(HTTPException) as caught:
        await acknowledge_reminder("reminder-1", SimpleNamespace(id="patient-1"), db)

    assert caught.value.status_code == 409
    assert event.status == status
    assert event.acknowledged_at is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_sent_reminder_acknowledgement_returns_persisted_server_state() -> None:
    event = _event("sent")
    db = _Session(event)

    result = await acknowledge_reminder(
        "reminder-1", SimpleNamespace(id="patient-1"), db
    )

    assert result["id"] == "reminder-1"
    assert result["status"] == "acknowledged"
    assert datetime.fromisoformat(result["acknowledged_at"]).tzinfo is not None
    assert event.status == "acknowledged"
    assert event.acknowledged_at is not None
    assert db.commits == 1
    assert db.statements[0]._for_update_arg is not None


@pytest.mark.asyncio
async def test_repeated_acknowledgement_is_idempotent() -> None:
    original_time = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
    event = _event("acknowledged", original_time)
    db = _Session(event)

    result = await acknowledge_reminder(
        "reminder-1", SimpleNamespace(id="patient-1"), db
    )

    assert result["status"] == "acknowledged"
    assert result["acknowledged_at"] == original_time.isoformat()
    assert event.acknowledged_at is original_time
    assert db.commits == 0


@pytest.mark.asyncio
async def test_unknown_reminder_is_not_acknowledged() -> None:
    db = _Session(None)

    with pytest.raises(HTTPException) as caught:
        await acknowledge_reminder(
            "missing", SimpleNamespace(id="patient-1"), db
        )

    assert caught.value.status_code == 404
    assert db.commits == 0


@pytest.mark.asyncio
async def test_reminder_list_defaults_to_all_statuses_and_uses_bounded_pagination() -> None:
    event = _event("sent")
    db = _Session([event])

    result = await list_reminders(SimpleNamespace(id="patient-1"), db=db)

    statement = db.statements[0]
    assert len(statement._where_criteria) == 1
    assert statement._limit_clause.value == 21
    assert result["items"][0]["status"] == "sent"
    assert result["items"][0]["retry_count"] == 0
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_reminder_list_uses_stable_bounded_cursor_and_returns_next_cursor() -> None:
    events = [
        _event("sent")
        for _ in range(51)
    ]
    for index, event in enumerate(events):
        event.id = str(UUID(int=index + 1))
        event.scheduled_at = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
    db = _Session(events)

    result = await list_reminders(
        SimpleNamespace(id="patient-1"),
        limit=50,
        cursor_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
        cursor_id=UUID(int=100),
        db=db,
    )

    statement = db.statements[0]
    assert len(statement._where_criteria) == 2
    assert statement._limit_clause.value == 51
    assert len(result["items"]) == 50
    assert result["next_cursor"] == {
        "scheduled_at": events[49].scheduled_at.isoformat(),
        "id": events[49].id,
    }


@pytest.mark.asyncio
async def test_reminder_cursor_requires_both_timezone_aware_fields() -> None:
    with pytest.raises(HTTPException) as missing_id:
        await list_reminders(
            SimpleNamespace(id="patient-1"),
            cursor_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
            db=_Session([]),
        )
    assert missing_id.value.status_code == 422

    with pytest.raises(HTTPException) as naive_time:
        await list_reminders(
            SimpleNamespace(id="patient-1"),
            cursor_at=datetime(2026, 9, 27, 9),
            cursor_id=UUID(int=1),
            db=_Session([]),
        )
    assert naive_time.value.status_code == 422
