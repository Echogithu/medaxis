"""新增独立患者报告与有序原件；不迁移或触发旧解析任务。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '8a3d7f1c9e20'
down_revision = '7d2c9e4a1b60'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('patient_reports',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('patient_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('institution', sa.String(200), nullable=False),
        sa.Column('examination_date', sa.Date()), sa.Column('report_date', sa.Date()),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('ownership_declared', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('patient_id', 'request_id', name='uq_report_patient_request'),
        sa.CheckConstraint("category IN ('lab', 'imaging', 'other')", name='ck_report_category'),
        sa.CheckConstraint('revision >= 0 AND source_version >= 1', name='ck_report_revision'))
    op.create_index('ix_report_patient_created', 'patient_reports', ['patient_id', 'created_at', 'id'])
    op.create_index('ix_report_patient_content', 'patient_reports', ['patient_id', 'content_hash'])
    op.create_table('patient_report_files',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(50), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint('report_id', 'position', name='uq_report_file_position'),
        sa.CheckConstraint('position >= 0 AND byte_size > 0 AND page_count > 0', name='ck_report_file_bounds'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM patient_reports')).scalar_one():
        raise RuntimeError('报告归档非空，禁止直接删除患者原件。')
    op.drop_table('patient_report_files')
    op.drop_table('patient_reports')
