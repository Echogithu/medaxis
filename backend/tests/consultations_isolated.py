"""独立容器运行咨询迁移、API 和可选双端浏览器，不访问业务库。"""
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
ARTIFACT = ROOT / '.ai/tasks/2026-10-03-chat-doctor-handoff-entry'


def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    harness.ARTIFACT = ARTIFACT
    suffix = uuid4().hex[:10]
    container, database = f'medaxis-consultations-{suffix}', f'medaxis_test_consultations_{suffix}'
    port = harness.free_port()
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), PYTHONUTF8='1',
        SECRET_KEY=secrets.token_hex(32), API_KEY_MASTER_KEY=secrets.token_hex(32),
        MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', ENVIRONMENT='staging', DEFAULT_ADMIN_PASSWORD='', REDIS_URL='redis://127.0.0.1:6399/0')
    url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{database}"
    for key in ['DATABASE_URL', 'ASYNC_DATABASE_URL', 'TEST_DATABASE_URL']: env[key] = url
    started = False
    processes, handles = [], []
    try:
        harness.run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container, '-p', f'127.0.0.1:{port}:5432',
            '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}', 'pgvector/pgvector:pg17'], env, 'consultation-container')
        started = True
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda c: c.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99: raise
                time.sleep(.2)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'consultation-migration')
        harness.run([sys.executable, '-m', 'alembic', 'downgrade', 'd4e5f6a7b8c9'], env, 'consultation-empty-downgrade')
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'consultation-reupgrade')
        harness.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '--tb=short', 'tests/test_consultations.py'], env, 'consultation-pytest')
        print((ARTIFACT/'consultation-pytest.log').read_text(encoding='utf-8')[-1300:], flush=True)
        if '--browser' in sys.argv:
            demo_database = f'medaxis_demo_e2e_consultation_{suffix}'
            asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda c: c.execute(f'CREATE DATABASE "{demo_database}"')))
            demo_url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{demo_database}"
            for key in ['DATABASE_URL', 'ASYNC_DATABASE_URL', 'TEST_DATABASE_URL']: env[key] = demo_url
            harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'consultation-browser-migration')
            os.environ.update(env)
            from tests.consultations_seed import seed
            env.update(asyncio.run(seed(demo_url)))
            api_port, web_port = harness.free_port(), harness.free_port()
            env.update(DEMO_API_PORT=str(api_port), CONSULTATION_API_URL=f'http://127.0.0.1:{api_port}', CONSULTATION_WEB_URL=f'http://127.0.0.1:{web_port}')
            for command, cwd, logfile in [
                ([sys.executable, '-m', 'tests.patient_demo_server'], BACKEND, 'consultation-api.log'),
                (['node', str(ROOT/'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], ROOT/'frontend', 'consultation-vite.log'),
            ]:
                handle = (ARTIFACT/logfile).open('w', encoding='utf-8'); handles.append(handle)
                processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=harness.HIDDEN))
            harness.wait_http(env['CONSULTATION_API_URL']+'/health', processes[0]); harness.wait_http(env['CONSULTATION_WEB_URL'], processes[1])
            browser_python = os.getenv('CONSULTATION_BROWSER_PYTHON') or shutil.which('python') or sys.executable
            harness.run([browser_python, '-m', 'tests.consultations_browser'], env, 'consultation-browser')
            print((ARTIFACT/'consultation-browser.log').read_text(encoding='utf-8')[-1800:], flush=True)
            rejected = subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', 'd4e5f6a7b8c9'], cwd=BACKEND, env=env,
                capture_output=True, text=True, encoding='utf-8', creationflags=harness.HIDDEN)
            assert rejected.returncode != 0 and '咨询记录非空' in rejected.stderr
            print('consultation-populated-downgrade: rejected as expected', flush=True)
        print('CONSULTATIONS_ISOLATED_PASS', flush=True)
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


if __name__ == '__main__':
    main()
