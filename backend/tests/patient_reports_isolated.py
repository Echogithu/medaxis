"""随机专用容器运行报告迁移/API/浏览器；只清理本脚本创建的资源。"""
import asyncio
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import asyncpg
from tests import profile_chain_isolated as harness

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
ARTIFACT = ROOT / '.ai/tasks/2026-10-03-patient-reports/artifacts/t2'


def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    harness.ARTIFACT = ARTIFACT
    suffix = uuid4().hex[:10]
    container = f'medaxis-reports-test-{suffix}'
    database, demo = f'medaxis_test_reports_{suffix}', f'medaxis_demo_e2e_reports_{suffix}'
    port, api_port, web_port = harness.free_port(), harness.free_port(), harness.free_port()
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), PYTHONUTF8='1',
        SECRET_KEY=secrets.token_hex(32), API_KEY_MASTER_KEY=secrets.token_hex(32),
        MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', ENVIRONMENT='staging', DEFAULT_ADMIN_PASSWORD='',
        MEDAXIS_DEMO_REDIS_MODE='substitute', REDIS_URL='redis://127.0.0.1:6399/0', DEMO_API_PORT=str(api_port))
    def point(db):
        url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{db}"
        for key in ['DATABASE_URL', 'ASYNC_DATABASE_URL', 'TEST_DATABASE_URL']: env[key] = url
    processes, handles, started = [], [], False
    try:
        harness.run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container,
            '-p', f'127.0.0.1:{port}:5432', '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}',
            'pgvector/pgvector:pg17'], env, 'container-start')
        started = True
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda c: c.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99: raise
                time.sleep(.2)
        point(database)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', '7d2c9e4a1b60'], env, 'migration-before')
        user_id, record_id = uuid4(), uuid4()
        async def legacy(conn):
            await conn.execute("""INSERT INTO users (id,email,full_name,role,status,is_verified,created_at,updated_at)
                VALUES ($1,$2,'归档迁移合成患者','PATIENT','ACTIVE',false,now(),now())""", user_id, f'{suffix}@example.invalid')
            await conn.execute("""INSERT INTO patient_health_measurements(id,patient_id,heart_rate,recorded_at,created_at)
                VALUES ($1,$2,72,now(),now())""", record_id, user_id)
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, legacy))
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-upgrade')
        harness.run([sys.executable, '-m', 'alembic', 'downgrade', '7d2c9e4a1b60'], env, 'migration-empty-downgrade')
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-reupgrade')
        async def guard(conn):
            assert 72 == await conn.fetchval('SELECT heart_rate FROM patient_health_measurements WHERE id=$1', record_id)
            await conn.execute("""INSERT INTO patient_reports (id,patient_id,request_id,request_fingerprint,content_hash,
                title,category,institution,notes,ownership_declared,revision,source_version,created_at,updated_at)
                VALUES ($1,$2,$3,$4,$4,'合成迁移保护归档','other','','',true,0,1,now(),now())""", uuid4(), user_id, uuid4(), '0'*64)
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, guard))
        rejected = subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', '7d2c9e4a1b60'], cwd=BACKEND,
            env=env, capture_output=True, text=True, encoding='utf-8', creationflags=harness.HIDDEN)
        assert rejected.returncode != 0 and '报告归档非空' in rejected.stderr
        assert 1 == asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database,
            lambda c: c.fetchval('SELECT count(*) FROM patient_reports')))
        (ARTIFACT/'migration-guard.log').write_text('Populated report downgrade rejected; legacy measurement and archive preserved.\n', encoding='utf-8')
        print('migration: empty downgrade, preserved legacy, populated downgrade rejected', flush=True)
        if '--browser-only' not in sys.argv:
            harness.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '--tb=short',
                'tests/test_patient_reports.py', 'tests/test_report_files.py'], env, 'pytest-reports')
            print((ARTIFACT/'pytest-reports.log').read_text(encoding='utf-8')[-1500:], flush=True)
        if '--api-only' in sys.argv:
            print('REPORTS_API_ISOLATED_PASS', flush=True)
            return
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda c: c.execute(f'CREATE DATABASE "{demo}"')))
        point(demo)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-browser')
        os.environ.update(env)
        async def seed():
            from app.core.security import create_access_token
            from app.db.session import async_session_maker, async_engine
            from app.models.user import User, UserRole, UserStatus
            from tests.report_samples import sample_image, text_pdf
            async with async_session_maker() as db:
                tokens = []
                for label in ['本人', '另一个账号']:
                    user = User(email=f'reports-browser-{uuid4()}@example.invalid', full_name=f'报告合成{label}',
                                role=UserRole.PATIENT, status=UserStatus.ACTIVE, hashed_password='unused')
                    db.add(user); await db.flush()
                    tokens.append(create_access_token(str(user.id), platform='web'))
                await db.commit()
            await async_engine.dispose()
            (ARTIFACT/'report-one.png').write_bytes(sample_image())
            (ARTIFACT/'report-two.png').write_bytes(sample_image('PNG', chinese=True))
            (ARTIFACT/'report-three.pdf').write_bytes(text_pdf(count=2))
            (ARTIFACT/'broken.png').write_bytes(b'\x89PNG\r\n\x1a\ninvalid')
            return tokens
        env['REPORTS_BROWSER_TOKEN'], env['REPORTS_OTHER_TOKEN'] = asyncio.run(seed())
        env.update(REPORTS_API_URL=f'http://127.0.0.1:{api_port}', REPORTS_WEB_URL=f'http://127.0.0.1:{web_port}')
        for command, cwd, log in [
            ([sys.executable, '-m', 'tests.patient_demo_server'], BACKEND, 'reports-api.log'),
            (['node', str(ROOT/'frontend/tests/patientReportsDevServer.mjs')], ROOT/'frontend', 'reports-vite.log')]:
            handle = (ARTIFACT/log).open('w', encoding='utf-8'); handles.append(handle)
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=harness.HIDDEN))
        harness.wait_http(f'http://127.0.0.1:{api_port}/health', processes[0])
        harness.wait_http(f'http://127.0.0.1:{web_port}', processes[1])
        browser_python = os.getenv('PROFILE_BROWSER_PYTHON') or shutil.which('python') or sys.executable
        harness.run([browser_python, '-m', 'tests.patient_reports_browser'], env, 'browser-reports')
        print((ARTIFACT/'browser-reports.log').read_text(encoding='utf-8')[-2000:], flush=True)
        print('REPORTS_CHAIN_ISOLATED_PASS', flush=True)
    finally:
        for process in reversed(processes):
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
        if started:
            result = subprocess.run(['docker', 'stop', container], capture_output=True, creationflags=harness.HIDDEN)
            print(f'owned-container-cleanup: exit={result.returncode}', flush=True)


if __name__ == '__main__': main()
