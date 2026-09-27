"""Store versioned, patient-reviewed case preparation snapshots."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_preparation_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("package", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_case_preparation_version_positive"),
        sa.CheckConstraint("revision > 0", name="ck_case_preparation_revision_positive"),
        sa.CheckConstraint(
            "state IN ('ready_for_review', 'needs_reassessment')",
            name="ck_case_preparation_state",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["medical_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "version", name="uq_case_preparation_case_version"),
        sa.UniqueConstraint("case_id", "source_fingerprint", name="uq_case_preparation_source"),
    )
    op.create_index(
        "ix_case_preparation_case_updated",
        "case_preparation_packages",
        ["case_id", "updated_at"],
    )


def downgrade() -> None:
    row_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM case_preparation_packages")
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            "Cannot downgrade while patient preparation snapshots exist; "
            "export or remove these snapshots before dropping the table."
        )
    op.drop_index("ix_case_preparation_case_updated", table_name="case_preparation_packages")
    op.drop_table("case_preparation_packages")
