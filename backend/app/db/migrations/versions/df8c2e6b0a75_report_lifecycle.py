"""回收站及独立管理提交墓碑。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'df8c2e6b0a75'
down_revision = 'ce7b1d5a9f64'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('patient_reports', sa.Column('trashed_at', sa.DateTime(timezone=True)))
    op.add_column('patient_reports', sa.Column('lifecycle_revision', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_report_upload_result', 'patient_report_upload_submissions', ['report_id'])
    op.create_table('patient_report_lifecycle_submissions',
        sa.Column('patient_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('request_id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('target_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('trash', 'restore', 'purge')", name='ck_report_lifecycle_kind'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM patient_report_lifecycle_submissions) OR EXISTS(SELECT 1 FROM patient_reports WHERE trashed_at IS NOT NULL OR lifecycle_revision <> 0)')).scalar_one():
        raise RuntimeError('回收站或管理提交记录非空，禁止丢弃恢复和删除历史。')
    op.drop_table('patient_report_lifecycle_submissions')
    op.drop_index('ix_report_upload_result', table_name='patient_report_upload_submissions')
    op.drop_column('patient_reports', 'lifecycle_revision')
    op.drop_column('patient_reports', 'trashed_at')
