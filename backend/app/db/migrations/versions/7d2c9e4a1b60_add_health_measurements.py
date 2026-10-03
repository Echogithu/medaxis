"""新增患者自报健康指标历史。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = '7d2c9e4a1b60'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('patient_health_measurements',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('patient_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('systolic', sa.Integer()), sa.Column('diastolic', sa.Integer()),
        sa.Column('heart_rate', sa.Integer()), sa.Column('weight', sa.Float()),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('(systolic IS NULL AND diastolic IS NULL) OR (systolic IS NOT NULL AND diastolic IS NOT NULL AND systolic > diastolic AND systolic BETWEEN 40 AND 300 AND diastolic BETWEEN 20 AND 200)', name='ck_measurement_pressure'),
        sa.CheckConstraint('heart_rate IS NULL OR heart_rate BETWEEN 20 AND 250', name='ck_measurement_heart_rate'),
        sa.CheckConstraint('weight IS NULL OR weight BETWEEN 2 AND 500', name='ck_measurement_weight'),
        sa.CheckConstraint('systolic IS NOT NULL OR heart_rate IS NOT NULL OR weight IS NOT NULL', name='ck_measurement_content'))
    op.create_index('ix_measurement_patient_recorded', 'patient_health_measurements', ['patient_id', 'recorded_at', 'id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM patient_health_measurements')).scalar_one():
        raise RuntimeError('指标记录非空，禁止直接删除患者健康历史。')
    op.drop_table('patient_health_measurements')
