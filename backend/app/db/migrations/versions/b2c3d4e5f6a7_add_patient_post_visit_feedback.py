"""Add versioned patient-owned post-visit feedback."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_post_visit_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_post_visit_feedback_version_positive"),
        sa.CheckConstraint("revision > 0", name="ck_post_visit_feedback_revision_positive"),
        sa.ForeignKeyConstraint(["case_id"], ["medical_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "version", name="uq_post_visit_feedback_case_version"),
    )
    op.create_index(
        "ix_post_visit_feedback_case_updated",
        "patient_post_visit_feedback",
        ["case_id", "updated_at"],
    )


def downgrade() -> None:
    row_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM patient_post_visit_feedback")
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            "Cannot downgrade while patient post-visit feedback exists; "
            "export or remove feedback before dropping the table."
        )
    op.drop_index(
        "ix_post_visit_feedback_case_updated", table_name="patient_post_visit_feedback"
    )
    op.drop_table("patient_post_visit_feedback")
