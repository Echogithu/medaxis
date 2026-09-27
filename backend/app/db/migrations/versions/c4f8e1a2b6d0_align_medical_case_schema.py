"""Align medical case schema with the current ORM.

Revision ID: c4f8e1a2b6d0
Revises: a8b9c0d1e2f3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4f8e1a2b6d0"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CASE_STATUSES = (
    "PENDING_REVIEW",
    "IN_PROGRESS",
    "AWAITING_PATIENT",
    "RESOLVED",
    "ARCHIVED",
)
_LEGACY_CASE_STATUSES = ("ACTIVE", "CLOSED", "ARCHIVED")


def _status_counts(statuses: tuple[str, ...]) -> dict[str, int]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT status::text AS status, count(*) AS row_count "
            "FROM medical_cases WHERE status::text IN :statuses "
            "GROUP BY status::text"
        ).bindparams(sa.bindparam("statuses", expanding=True)),
        {"statuses": list(statuses)},
    )
    return {row.status: row.row_count for row in rows}


def upgrade() -> None:
    """Rename legacy columns and add the current ORM fields without dropping data."""
    legacy_rows = _status_counts(("ACTIVE", "CLOSED"))
    if legacy_rows:
        details = ", ".join(f"{name}={count}" for name, count in sorted(legacy_rows.items()))
        raise RuntimeError(
            "Cannot align medical_cases while legacy ACTIVE/CLOSED rows exist "
            f"({details}); no verified status mapping is available."
        )

    bind = op.get_bind()
    op.execute("ALTER TYPE casestatus RENAME TO casestatus_legacy")
    postgresql.ENUM(*_NEW_CASE_STATUSES, name="casestatus").create(bind)
    op.execute(
        "ALTER TABLE medical_cases ALTER COLUMN status TYPE casestatus "
        "USING status::text::casestatus"
    )
    postgresql.ENUM(name="casestatus_legacy").drop(bind)

    op.alter_column("medical_cases", "doctor_id", new_column_name="assigned_doctor_id")
    op.alter_column("medical_cases", "diagnosis_ai", new_column_name="ai_diagnosis_summary")
    op.alter_column("medical_cases", "diagnosis_doctor", new_column_name="doctor_diagnosis")
    op.alter_column("medical_cases", "closed_at", new_column_name="resolved_at")

    op.drop_index("ix_medical_cases_doctor_id", table_name="medical_cases")
    op.create_index(
        "ix_medical_cases_assigned_doctor_id",
        "medical_cases",
        ["assigned_doctor_id"],
        unique=False,
    )

    op.add_column("medical_cases", sa.Column("source_session_id", postgresql.UUID(as_uuid=True)))
    op.add_column("medical_cases", sa.Column("chief_complaint", sa.Text(), nullable=True))
    op.add_column("medical_cases", sa.Column("severity", sa.String(length=20), nullable=True))
    op.add_column(
        "medical_cases",
        sa.Column(
            "is_emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("medical_cases", "is_emergency", server_default=None)
    op.add_column("medical_cases", sa.Column("doctor_notes", sa.Text(), nullable=True))
    op.add_column(
        "medical_cases",
        sa.Column("treatment_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "medical_cases",
        sa.Column("follow_up_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_medical_cases_source_session_id",
        "medical_cases",
        ["source_session_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_medical_cases_source_session_id_agent_sessions",
        "medical_cases",
        "agent_sessions",
        ["source_session_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for column, comment in (
        ("patient_id", "Patient who owns this case"),
        ("assigned_doctor_id", "Doctor assigned to this case"),
        ("source_session_id", "AgentSession that produced the AI diagnosis"),
        ("chief_complaint", "Patient's chief complaint (from InterviewState)"),
        (
            "ai_diagnosis_summary",
            "AI diagnosis summary (from structured_output.primary_diagnosis)",
        ),
        ("severity", "mild / moderate / severe / emergency"),
        ("is_emergency", "Whether this is an emergency case"),
        ("doctor_diagnosis", "Doctor-confirmed or corrected diagnosis"),
        ("doctor_notes", "Doctor's clinical notes"),
        ("treatment_plan", "Treatment plan (structured JSON)"),
        ("follow_up_due_at", "Next follow-up due date"),
        ("resolved_at", "When the case was resolved"),
    ):
        op.alter_column("medical_cases", column, comment=comment)


def downgrade() -> None:
    """Restore the legacy shape only when no new-only data would be discarded."""
    bind = op.get_bind()
    non_legacy_statuses = _status_counts(
        ("PENDING_REVIEW", "IN_PROGRESS", "AWAITING_PATIENT", "RESOLVED")
    )
    if non_legacy_statuses:
        details = ", ".join(
            f"{name}={count}" for name, count in sorted(non_legacy_statuses.items())
        )
        raise RuntimeError(
            "Cannot downgrade medical_cases while new-only statuses exist "
            f"({details}); no verified reverse status mapping is available."
        )

    added_data = bind.execute(
        sa.text(
            "SELECT count(*) FROM medical_cases WHERE "
            "source_session_id IS NOT NULL OR chief_complaint IS NOT NULL "
            "OR severity IS NOT NULL OR is_emergency IS TRUE "
            "OR doctor_notes IS NOT NULL OR treatment_plan IS NOT NULL "
            "OR follow_up_due_at IS NOT NULL"
        )
    ).scalar_one()
    if added_data:
        raise RuntimeError(
            "Cannot downgrade medical_cases while T1-only fields contain data; "
            "restore from a verified backup or clear the new data deliberately first."
        )

    for column in (
        "patient_id",
        "assigned_doctor_id",
        "source_session_id",
        "chief_complaint",
        "ai_diagnosis_summary",
        "severity",
        "is_emergency",
        "doctor_diagnosis",
        "doctor_notes",
        "treatment_plan",
        "follow_up_due_at",
        "resolved_at",
    ):
        op.alter_column("medical_cases", column, comment=None)

    op.drop_constraint(
        "fk_medical_cases_source_session_id_agent_sessions",
        "medical_cases",
        type_="foreignkey",
    )
    op.drop_index("ix_medical_cases_source_session_id", table_name="medical_cases")
    for column in (
        "source_session_id",
        "chief_complaint",
        "severity",
        "is_emergency",
        "doctor_notes",
        "treatment_plan",
        "follow_up_due_at",
    ):
        op.drop_column("medical_cases", column)

    op.drop_index("ix_medical_cases_assigned_doctor_id", table_name="medical_cases")
    op.alter_column("medical_cases", "assigned_doctor_id", new_column_name="doctor_id")
    op.create_index(
        "ix_medical_cases_doctor_id",
        "medical_cases",
        ["doctor_id"],
        unique=False,
    )
    op.alter_column("medical_cases", "ai_diagnosis_summary", new_column_name="diagnosis_ai")
    op.alter_column("medical_cases", "doctor_diagnosis", new_column_name="diagnosis_doctor")
    op.alter_column("medical_cases", "resolved_at", new_column_name="closed_at")

    op.execute("ALTER TYPE casestatus RENAME TO casestatus_current")
    postgresql.ENUM(*_LEGACY_CASE_STATUSES, name="casestatus").create(bind)
    op.execute(
        "ALTER TABLE medical_cases ALTER COLUMN status TYPE casestatus "
        "USING status::text::casestatus"
    )
    postgresql.ENUM(name="casestatus_current").drop(bind)
