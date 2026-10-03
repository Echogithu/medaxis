"""新增患者主动授权的定向咨询与消息。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('consultations',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('case_id', pg.UUID(as_uuid=True), sa.ForeignKey('medical_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('patient_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('doctor_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('doctor_profile', pg.JSONB(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('snapshot', pg.JSONB(), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('pending','accepted','awaiting_patient','completed','declined','cancelled','unavailable')", name='ck_consultation_state'),
        sa.CheckConstraint('revision > 0', name='ck_consultation_revision'))
    op.create_index('uq_consultation_active_case', 'consultations', ['case_id'], unique=True,
                    postgresql_where=sa.text("state IN ('pending','accepted','awaiting_patient')"))
    op.create_index('ix_consultation_patient_updated', 'consultations', ['patient_id', 'updated_at'])
    op.create_index('ix_consultation_doctor_updated', 'consultations', ['doctor_id', 'updated_at'])
    op.create_table('consultation_messages',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('consultation_id', pg.UUID(as_uuid=True), sa.ForeignKey('consultations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('author_profile', pg.JSONB(), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('category', sa.String(32)),
        sa.Column('next_state', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_consultation_messages_consultation_id', 'consultation_messages', ['consultation_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM consultations')).scalar_one():
        raise RuntimeError('咨询记录非空，禁止直接删除患者授权和医患沟通历史。')
    op.drop_table('consultation_messages')
    op.drop_table('consultations')
