"""本人上传/复用提交receipt；删除结果不删除编号墓碑。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'ce7b1d5a9f64'
down_revision = 'bd6a0c4f2b53'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('patient_report_upload_submissions',
        sa.Column('patient_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('request_id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('report_id', pg.UUID(as_uuid=True), sa.ForeignKey('patient_reports.id', ondelete='SET NULL')),
        sa.Column('outcome', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("outcome IN ('archived', 'reused')", name='ck_report_upload_outcome'))
    # 老创建提交也留receipt，否则彻底删除后同一编号会重新创建报告。
    op.execute("""INSERT INTO patient_report_upload_submissions(patient_id,request_id,request_fingerprint,report_id,outcome,created_at)
        SELECT patient_id,request_id,request_fingerprint,id,'archived',created_at FROM patient_reports""")


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM patient_report_upload_submissions)')).scalar_one():
        raise RuntimeError('报告上传或复用提交记录非空，禁止丢弃重试及删除墓碑。')
    op.drop_table('patient_report_upload_submissions')
