"""add notifications and user attachment tables

Revision ID: a8b9c0d1e2f3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notification and doctor credential attachment tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Some installations created this table before it was tracked by Alembic.
    # Preserve that data and only create the table when it is genuinely absent.
    if not inspector.has_table("user_attachments"):
        op.create_table(
            "user_attachments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("file_url", sa.String(length=500), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("mime_type", sa.String(length=50), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("label", sa.String(length=100), nullable=True),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("verify_note", sa.String(length=255), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        )

    attachment_indexes = {
        index["name"] for index in inspector.get_indexes("user_attachments")
    }
    if "ix_user_attachments_user_id" not in attachment_indexes:
        op.create_index("ix_user_attachments_user_id", "user_attachments", ["user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "notification_type",
            postgresql.ENUM(
                "SYSTEM", "ANNOUNCEMENT", "DIRECT", "REMINDER",
                name="notificationtype",
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            postgresql.ENUM("HIGH", "MEDIUM", "LOW", name="notificationpriority"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("action_url", sa.String(length=512), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender_deleted", sa.Boolean(), nullable=False),
        sa.Column("recipient_deleted", sa.Boolean(), nullable=False),
        sa.Column("broadcast", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notifications_sender_id", "notifications", ["sender_id"])
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"])
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
    op.create_index("ix_notifications_broadcast", "notifications", ["broadcast"])
    op.create_index(
        "ix_notifications_recipient_inbox",
        "notifications",
        ["recipient_id", "recipient_deleted", "is_read", "created_at"],
    )
    op.create_index(
        "ix_notifications_sender_outbox",
        "notifications",
        ["sender_id", "sender_deleted", "created_at"],
    )


def downgrade() -> None:
    """Drop notification and attachment tables."""
    op.drop_index("ix_notifications_sender_outbox", table_name="notifications")
    op.drop_index("ix_notifications_recipient_inbox", table_name="notifications")
    op.drop_index("ix_notifications_broadcast", table_name="notifications")
    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_notifications_notification_type", table_name="notifications")
    op.drop_index("ix_notifications_recipient_id", table_name="notifications")
    op.drop_index("ix_notifications_sender_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_user_attachments_user_id", table_name="user_attachments")
    op.drop_table("user_attachments")
    sa.Enum(name="notificationpriority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notificationtype").drop(op.get_bind(), checkfirst=True)
