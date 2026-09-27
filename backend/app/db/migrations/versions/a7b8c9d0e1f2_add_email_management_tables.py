"""add email management tables

Revision ID: a7b8c9d0e1f2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create SMTP configuration, template, and delivery log tables."""
    op.create_table(
        "email_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("smtp_host", sa.String(length=255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("smtp_user", sa.String(length=255), nullable=False),
        sa.Column("smtp_password_encrypted", sa.String(length=512), nullable=False),
        sa.Column("smtp_from_email", sa.String(length=255), nullable=False),
        sa.Column("smtp_from_name", sa.String(length=255), nullable=False),
        sa.Column(
            "smtp_security",
            postgresql.ENUM("STARTTLS", "SSL", "NONE", name="smtpsecurity"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("test_status", sa.String(length=50), nullable=False),
        sa.Column("test_message", sa.Text(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "email_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("variables", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("name", name="uq_email_templates_name"),
    )

    op.create_table(
        "email_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_configurations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_preview", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("PENDING", "SENT", "FAILED", "RETRYING", name="emailsendstatus"),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_email_logs_recipient_email", "email_logs", ["recipient_email"])
    op.create_index("ix_email_logs_status", "email_logs", ["status"])
    op.create_index(
        "ix_email_logs_status_created",
        "email_logs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    """Drop email management tables and their enum types."""
    op.drop_index("ix_email_logs_status_created", table_name="email_logs")
    op.drop_index("ix_email_logs_status", table_name="email_logs")
    op.drop_index("ix_email_logs_recipient_email", table_name="email_logs")
    op.drop_table("email_logs")
    op.drop_table("email_templates")
    op.drop_table("email_configurations")
    sa.Enum(name="emailsendstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="smtpsecurity").drop(op.get_bind(), checkfirst=True)
