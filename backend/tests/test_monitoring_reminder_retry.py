"""合成 SMTP 失败时提醒的重试终态。"""

from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

import pytest

from app.tasks import monitoring


class _Result:
    def scalar_one_or_none(self):
        return "reminder-1"


class _Session:
    def __init__(self, event):
        self.event = event
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return _Result()

    async def get(self, _model, _event_id):
        return self.event

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_count", "expected_status", "expected_retry_count"),
    [(0, "pending", 1), (2, "failed", 3)],
)
async def test_delivery_failure_is_retryable_until_terminal_attempt(
    monkeypatch: pytest.MonkeyPatch,
    retry_count: int,
    expected_status: str,
    expected_retry_count: int,
) -> None:
    event = SimpleNamespace(
        patient_id="patient-1", status="in_flight", retry_count=retry_count, error_message=None
    )
    session = _Session(event)

    async def patient_is_not_busy(_db, _patient_id):
        return False

    async def fail_send(_db, _event):
        raise RuntimeError("synthetic mail failure")

    monkeypatch.setattr(monitoring, "_is_patient_busy", patient_is_not_busy)
    monkeypatch.setattr(monitoring, "_send_reminder_email", fail_send)

    outcome = await monitoring._claim_and_send("reminder-1", session_factory=lambda: session)

    assert outcome == "failed"
    assert event.status == expected_status
    assert event.retry_count == expected_retry_count
    assert event.error_message == "synthetic mail failure"


def test_sweeper_query_only_selects_retryable_pending_events() -> None:
    statement = monitoring._pending_events_query(datetime(2026, 9, 27, tzinfo=timezone.utc))
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "monitoring_events.status = 'pending'" in sql
    assert "coalesce(monitoring_events.retry_count, 0) < 3" in sql
    assert "LIMIT 50" in sql


def test_sweeper_treats_null_retry_count_as_zero_and_skips_exhausted_rows() -> None:
    now = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
    null_retry_id = UUID(int=1)
    exhausted_id = UUID(int=2)
    with create_engine("sqlite:///:memory:").connect() as connection:
        connection.execute(text(
            "CREATE TABLE monitoring_events "
            "(id TEXT PRIMARY KEY, status TEXT NOT NULL, scheduled_at DATETIME NOT NULL, retry_count INTEGER)"
        ))
        connection.execute(
            text(
                "INSERT INTO monitoring_events (id, status, scheduled_at, retry_count) "
                "VALUES (:id, 'pending', :scheduled_at, :retry_count)"
            ),
            [
                {"id": str(null_retry_id), "scheduled_at": "2026-09-27 08:00:00.000000", "retry_count": None},
                {"id": str(exhausted_id), "scheduled_at": "2026-09-27 08:00:00.000000", "retry_count": 3},
            ],
        )
        connection.commit()

        selected_ids = connection.execute(monitoring._pending_events_query(now)).scalars().all()

    assert selected_ids == [null_retry_id]
