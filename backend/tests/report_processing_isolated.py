"""仅新建随机合成PostgreSQL验证T3后端；不使用业务数据库或真实模型。"""
import asyncio
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import asyncpg
from tests import profile_chain_isolated as harness

ARTIFACT = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-patient-reports/artifacts/t3'


def main():
    suffix = uuid4().hex[:10]
    artifact = ARTIFACT / 'runs' / suffix
    artifact.mkdir(parents=True, exist_ok=True)
    harness.ARTIFACT = artifact
    print(f'processing-artifact: {artifact}', flush=True)
    container, database, port = f'medaxis-report-processing-test-{suffix}', f'medaxis_test_reports_{suffix}', harness.free_port()
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), SECRET_KEY=secrets.token_hex(32),
        API_KEY_MASTER_KEY=secrets.token_hex(32), PYTHONUTF8='1', ENVIRONMENT='staging', DEFAULT_ADMIN_PASSWORD='',
        MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', REDIS_URL='redis://127.0.0.1:6399/0')
    url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{database}"
    env.update(DATABASE_URL=url, ASYNC_DATABASE_URL=url, TEST_DATABASE_URL=url)
    started = False
    try:
        harness.run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container,
            '-p', f'127.0.0.1:{port}:5432', '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}',
            'pgvector/pgvector:pg17'], env, 'processing-container-start')
        started = True
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda db: db.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99: raise
                time.sleep(.2)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', '8a3d7f1c9e20'], env, 'processing-migration-before')
        patient_id, report_id = uuid4(), uuid4()
        async def legacy(db):
            await db.execute("""INSERT INTO users(id,email,full_name,role,status,is_verified,created_at,updated_at)
                VALUES($1,$2,'合成迁移患者','PATIENT','ACTIVE',false,now(),now())""", patient_id, f'{suffix}@example.invalid')
            await db.execute("""INSERT INTO patient_reports(id,patient_id,request_id,request_fingerprint,content_hash,
                title,category,institution,notes,ownership_declared,revision,source_version,created_at,updated_at)
                VALUES($1,$2,$3,$4,$4,'合成既有报告','lab','','',true,0,1,now(),now())""", report_id, patient_id, uuid4(), '0'*64)
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, legacy))
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'processing-migration-upgrade')
        harness.run([sys.executable, '-m', 'alembic', 'downgrade', '8a3d7f1c9e20'], env, 'processing-migration-empty-downgrade')
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'processing-migration-reupgrade')
        async def populated(db):
            assert '合成既有报告' == await db.fetchval('SELECT title FROM patient_reports WHERE id=$1', report_id)
            await db.execute("UPDATE patient_reports SET workflow='{\"revision\":1}'::jsonb WHERE id=$1", report_id)
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, populated))
        result = subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', '8a3d7f1c9e20'],
            env=env, cwd=harness.BACKEND, capture_output=True, text=True, encoding='utf-8', creationflags=harness.HIDDEN)
        assert result.returncode != 0 and '禁止直接丢弃患者工作区' in result.stderr
        (artifact/'processing-migration-guard.log').write_text('Workspace downgrade refused; existing report preserved.\n', encoding='utf-8')
        test_files = ['tests/test_report_processing.py', 'tests/test_report_candidates.py']
        if '--targeted' not in sys.argv:
            test_files.append('tests/test_patient_reports.py')
        harness.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '--tb=short', *test_files], env, 'pytest-processing')
        print((artifact/'pytest-processing.log').read_text(encoding='utf-8')[-2000:], flush=True)
        print('REPORT_PROCESSING_BACKEND_ISOLATED_PASS', flush=True)
    finally:
        if started:
            result = subprocess.run(['docker', 'stop', container], capture_output=True, creationflags=harness.HIDDEN)
            print(f'owned-processing-container-cleanup: exit={result.returncode}', flush=True)


if __name__ == '__main__': main()
