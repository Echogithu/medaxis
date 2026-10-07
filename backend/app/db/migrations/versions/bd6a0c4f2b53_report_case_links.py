"""独立患者报告的病例引用及提交重放，不改变医生授权。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'bd6a0c4f2b53'
down_revision = 'ac5f9b3e1a42'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('patient_reports', sa.Column('links_revision', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('patient_report_case_links',
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('medical_cases.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('source_version', sa.Integer(), nullable=False), sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('review_version_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_report_review_versions.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('source_version > 0', name='ck_report_link_source'))
    op.create_index('ix_report_link_case', 'patient_report_case_links', ['case_id', 'report_id'])
    op.create_table('patient_report_management_operations',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_id', pg.UUID(as_uuid=True), nullable=False), sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('report_id', 'request_id', name='uq_report_management_request'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM patient_report_case_links) OR EXISTS(SELECT 1 FROM patient_report_management_operations) OR EXISTS(SELECT 1 FROM patient_reports WHERE links_revision <> 0)')).scalar_one():
        raise RuntimeError('报告病例引用或提交记录非空，禁止直接丢弃关联历史。')
    op.drop_table('patient_report_management_operations')
    op.drop_table('patient_report_case_links')
    op.drop_column('patient_reports', 'links_revision')
