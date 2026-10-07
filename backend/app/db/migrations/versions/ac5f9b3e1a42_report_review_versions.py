"""患者人工草稿/确认历史；不丢弃已有原件及整理工作区。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'ac5f9b3e1a42'
down_revision = '9b4e8a2d0f31'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('patient_reports', sa.Column('review_state', pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_table('patient_report_review_versions',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(12), nullable=False), sa.Column('category', sa.String(20), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False), sa.Column('source_epoch', sa.Integer(), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('based_on_version_id', pg.UUID(as_uuid=True)), sa.Column('candidate_job_id', pg.UUID(as_uuid=True)),
        sa.Column('confirmed_draft_id', pg.UUID(as_uuid=True)), sa.Column('payload', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('report_id', 'request_id', name='uq_report_review_request'),
        sa.UniqueConstraint('report_id', 'revision', name='uq_report_review_revision'),
        sa.CheckConstraint("kind IN ('draft', 'confirmed')", name='ck_report_review_kind'),
        sa.CheckConstraint('revision > 0 AND source_version > 0 AND source_epoch >= 0', name='ck_report_review_bounds'))
    op.create_index('ix_report_review_history', 'patient_report_review_versions', ['report_id', 'revision'])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS(SELECT 1 FROM patient_report_review_versions) OR EXISTS(SELECT 1 FROM patient_reports WHERE review_state <> '{}'::jsonb)")).scalar_one():
        raise RuntimeError('报告核对版本或来源记录非空，禁止直接丢弃患者草稿和确认历史。')
    op.drop_table('patient_report_review_versions')
    op.drop_column('patient_reports', 'review_state')
