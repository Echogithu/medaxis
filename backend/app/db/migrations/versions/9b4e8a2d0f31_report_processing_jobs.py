"""报告本地识字和逐次同意任务；已有原件保持独立。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '9b4e8a2d0f31'
down_revision = '8a3d7f1c9e20'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('patient_reports', sa.Column('workflow', pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_table('patient_report_jobs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('lease', pg.UUID(as_uuid=True)),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('dispatch_started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('error_code', sa.String(40)), sa.Column('error_message', sa.String(200)),
        sa.Column('input', pg.JSONB(), nullable=False), sa.Column('result', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('report_id', 'request_id', name='uq_report_job_request'),
        sa.CheckConstraint("kind IN ('extract', 'ai')", name='ck_report_job_kind'),
        sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')", name='ck_report_job_status'),
        sa.CheckConstraint('attempts >= 0 AND source_version >= 1', name='ck_report_job_bounds'))
    op.create_index('ix_report_job_pending', 'patient_report_jobs', ['status', 'updated_at'])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT EXISTS(SELECT 1 FROM patient_report_jobs) OR EXISTS(SELECT 1 FROM patient_reports WHERE workflow <> \'{}\'::jsonb)')).scalar_one():
        raise RuntimeError('报告整理任务或预览非空，禁止直接丢弃患者工作区。')
    op.drop_table('patient_report_jobs')
    op.drop_column('patient_reports', 'workflow')
