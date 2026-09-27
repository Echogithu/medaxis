"""Persist uploaded medical files and parser state.

Revision ID: e7f8a9b0c1d2
Revises: c4f8e1a2b6d0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c4f8e1a2b6d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_parse_tasks",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("parse_method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("file_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_guest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_session_id", sa.String(length=255), nullable=True),
        sa.Column("source_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(owner_user_id IS NOT NULL AND owner_guest_id IS NULL) OR "
            "(owner_user_id IS NULL AND owner_guest_id IS NOT NULL)",
            name="ck_document_parse_exactly_one_owner",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_document_parse_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_guest_id"], ["guest_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_session_id"], ["agent_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["case_id"], ["medical_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("file_id"),
    )
    op.create_index("ix_document_parse_owner_user", "document_parse_tasks", ["owner_user_id"])
    op.create_index("ix_document_parse_owner_guest", "document_parse_tasks", ["owner_guest_id"])
    op.create_index("ix_document_parse_client_session", "document_parse_tasks", ["client_session_id"])
    op.create_index("ix_document_parse_source_session", "document_parse_tasks", ["source_session_id"])
    op.create_index("ix_document_parse_case", "document_parse_tasks", ["case_id"])
    op.create_index(
        "ix_document_parse_user_client", "document_parse_tasks", ["owner_user_id", "client_session_id"]
    )
    op.create_index(
        "ix_document_parse_guest_client", "document_parse_tasks", ["owner_guest_id", "client_session_id"]
    )


def downgrade() -> None:
    row_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM document_parse_tasks")
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            "Cannot downgrade while persisted patient uploads exist; "
            "delete or export these materials before removing their storage table."
        )
    op.drop_index("ix_document_parse_guest_client", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_user_client", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_case", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_source_session", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_client_session", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_owner_guest", table_name="document_parse_tasks")
    op.drop_index("ix_document_parse_owner_user", table_name="document_parse_tasks")
    op.drop_table("document_parse_tasks")
