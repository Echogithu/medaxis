"""Add quota and idempotent result records for guest model submissions."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guest_model_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quota_refunded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_guest_model_submission_status",
        ),
        sa.ForeignKeyConstraint(
            ["guest_session_id"], ["guest_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guest_session_id", "submission_id", name="uq_guest_model_submission_key"
        ),
    )
    op.create_index(
        "ix_guest_model_submission_session_created",
        "guest_model_submissions",
        ["guest_session_id", "created_at"],
    )


def downgrade() -> None:
    row_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM guest_model_submissions")
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            "Cannot downgrade while guest submission results exist; "
            "wait for guest-session cleanup before dropping the table."
        )
    op.drop_index(
        "ix_guest_model_submission_session_created", table_name="guest_model_submissions"
    )
    op.drop_table("guest_model_submissions")
