"""保存人工档案的来源、状态和修订信息；不倒填历史来源。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("patient_health_profiles", sa.Column(
        "record_metadata", postgresql.JSONB, nullable=True, server_default=sa.text("'{}'::jsonb"),
    ))


def downgrade():
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM patient_health_profiles WHERE record_metadata IS NOT NULL AND record_metadata <> '{}'::jsonb"
    )).scalar_one()
    if count:
        raise RuntimeError("档案已有来源/修订数据，请先导出并确认恢复方案，不能直接删除元数据列")
    op.drop_column("patient_health_profiles", "record_metadata")
