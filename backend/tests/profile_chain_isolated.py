"""独立容器验证档案迁移、API 与浏览器；不连接现有业务数据库。

运行：.venv/Scripts/python.exe -m tests.profile_chain_isolated
要求 Docker 已有 pgvector/pgvector:pg17 镜像，前端依赖及 Edge 已安装。
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4
from urllib.request import urlopen

import asyncpg

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
ARTIFACT = ROOT / '.ai/tasks/2026-10-03-health-followup-workspace/profile'
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run(command, env, label, *, expected=0):
    result = subprocess.run(command, cwd=BACKEND, env=env, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', creationflags=HIDDEN)
    output = (result.stdout + result.stderr).replace(env['POSTGRES_PASSWORD'], '[redacted]')
    (ARTIFACT / f'{label}.log').write_text(output, encoding='utf-8')
    print(f'{label}: exit={result.returncode}', flush=True)
    if result.returncode != expected:
        # 应用日志可能包含配置，失败只打印最后几行，且去除本次生成的密码。
        detail = (result.stdout + result.stderr)[-7000:].replace(env['POSTGRES_PASSWORD'], '[redacted]')
        print(detail, flush=True)
        raise RuntimeError(f'{label} failed; see task log')
    return result


async def sql(port, password, database, operation):
    connection = await asyncpg.connect(host='127.0.0.1', port=port, user='postgres', password=password, database=database)
    try:
        return await operation(connection)
    finally:
        await connection.close()


def wait_http(url, process):
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('Owned test server exited; inspect task server log')
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.2)
    raise RuntimeError('Owned test server did not become ready')


def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    suffix = uuid4().hex[:10]
    container = f'medaxis-profile-test-{suffix}'
    database = f'medaxis_test_profile_{suffix}'
    demo_database = f'medaxis_demo_e2e_profile_{suffix}'
    port, api_port, web_port = free_port(), free_port(), free_port()
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), PYTHONUTF8='1',
               SECRET_KEY=secrets.token_hex(32), API_KEY_MASTER_KEY=secrets.token_hex(32),
               MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', ENVIRONMENT='staging',
               DEFAULT_ADMIN_PASSWORD='', MEDAXIS_DEMO_REDIS_MODE='substitute',
               REDIS_URL='redis://127.0.0.1:6399/0', DEMO_API_PORT=str(api_port))
    def point_to(db_name):
        url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{db_name}"
        for key in ['DATABASE_URL', 'ASYNC_DATABASE_URL', 'TEST_DATABASE_URL']:
            env[key] = url
    processes, handles = [], []
    started = False
    try:
        browser_python = os.getenv('PROFILE_BROWSER_PYTHON') or shutil.which('python') or sys.executable
        run([browser_python, '-c', 'import playwright.sync_api'], env, 'browser-runtime')
        run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container,
             '-p', f'127.0.0.1:{port}:5432', '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}',
             'pgvector/pgvector:pg17'], env, 'container-start')
        started = True
        for attempt in range(100):
            try:
                asyncio.run(sql(port, env['POSTGRES_PASSWORD'], database, lambda conn: conn.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99:
                    raise
                time.sleep(.2)
        point_to(database)
        run([sys.executable, '-m', 'alembic', 'upgrade', 'c3d4e5f6a7b8'], env, 'migration-before')
        patient_id, profile_id = uuid4(), uuid4()
        async def seed_legacy(conn):
            await conn.execute("""INSERT INTO users
                (id, email, full_name, role, status, is_verified, created_at, updated_at)
                VALUES ($1, $2, '迁移合成患者', 'PATIENT', 'ACTIVE', false, now(), now())""",
                patient_id, f'{suffix}@example.com')
            await conn.execute("""INSERT INTO patient_health_profiles
                (id, patient_id, last_updated, chronic_diseases, current_medications)
                VALUES ($1, $2, now(), '[{"name":"迁移合成慢性病"}]', '[{"name":"迁移合成药"}]')""", profile_id, patient_id)
        asyncio.run(sql(port, env['POSTGRES_PASSWORD'], database, seed_legacy))
        run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-upgrade')
        async def verify_legacy(conn):
            row = await conn.fetchrow('SELECT chronic_diseases, current_medications, record_metadata FROM patient_health_profiles WHERE id=$1', profile_id)
            assert json.loads(row['chronic_diseases']) == [{'name': '迁移合成慢性病'}]
            assert json.loads(row['current_medications']) == [{'name': '迁移合成药'}]
            assert json.loads(row['record_metadata']) == {}
        asyncio.run(sql(port, env['POSTGRES_PASSWORD'], database, verify_legacy))
        run([sys.executable, '-m', 'alembic', 'downgrade', 'c3d4e5f6a7b8'], env, 'migration-empty-downgrade')
        run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-reupgrade')
        asyncio.run(sql(port, env['POSTGRES_PASSWORD'], database,
            lambda conn: conn.execute("UPDATE patient_health_profiles SET record_metadata='{" + '"revision":1}' + "'::jsonb WHERE id=$1", profile_id)))
        rejected = subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', 'c3d4e5f6a7b8'],
            cwd=BACKEND, env=env, capture_output=True, text=True, encoding='utf-8', creationflags=HIDDEN)
        assert rejected.returncode != 0 and '不能直接删除元数据列' in rejected.stderr
        (ARTIFACT / 'migration-guard.log').write_text('Populated metadata downgrade rejected as expected.\n', encoding='utf-8')
        print('migration: legacy preserved, empty downgrade passed, populated downgrade rejected', flush=True)
        if '--browser-only' not in sys.argv:
            run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '--tb=short',
                 'tests/test_patient_profile_records.py', 'tests/test_patient_profile_api.py', 'tests/test_health_measurements.py',
                 'tests/test_intent_latency.py', 'tests/test_case_preparation.py', 'tests/test_case_preparation_semantics.py'], env, 'pytest-profile')
            print((ARTIFACT / 'pytest-profile.log').read_text(encoding='utf-8')[-800:], flush=True)
        asyncio.run(sql(port, env['POSTGRES_PASSWORD'], database,
            lambda conn: conn.execute(f'CREATE DATABASE "{demo_database}"')))
        point_to(demo_database)
        run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-browser')
        # 只修改验收脚本自身进程的环境，种子函数与演示服务器使用同一隔离目标。
        from tests.database_safety import validate_demo_database
        validate_demo_database(env['DATABASE_URL'])
        os.environ.update(env)
        async def seed_browser():
            from app.core.security import create_access_token
            from app.db.session import async_session_maker, async_engine
            from app.models.user import User, UserRole, UserStatus
            from app.models.agent import PatientHealthProfile
            async with async_session_maker() as db:
                user = User(email=f'profile-browser-{uuid4()}@example.com', full_name='档案浏览器合成患者',
                    role=UserRole.PATIENT, status=UserStatus.ACTIVE, hashed_password='unused', age_years=30)
                db.add(user)
                await db.commit()
                token = create_access_token(str(user.id), platform='web')
                legacy = User(email=f'profile-legacy-{uuid4()}@example.com', full_name='旧档案合成患者',
                    role=UserRole.PATIENT, status=UserStatus.ACTIVE, hashed_password='unused')
                db.add(legacy)
                await db.flush()
                db.add(PatientHealthProfile(patient_id=legacy.id, chronic_diseases=[{'name': '历史合成慢性病'}],
                    current_medications=[{'name': '历史合成药'}], record_metadata={}))
                await db.commit()
                legacy_token = create_access_token(str(legacy.id), platform='web')
            await async_engine.dispose()
            return token, legacy_token
        env['PROFILE_BROWSER_TOKEN'], env['PROFILE_LEGACY_TOKEN'] = asyncio.run(seed_browser())
        env.update(PROFILE_API_URL=f'http://127.0.0.1:{api_port}', PROFILE_WEB_URL=f'http://127.0.0.1:{web_port}')
        for command, cwd, logfile in [
            ([sys.executable, '-m', 'tests.patient_demo_server'], BACKEND, 'profile-api.log'),
            (['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], ROOT / 'frontend', 'profile-vite.log'),
        ]:
            handle = (ARTIFACT / logfile).open('w', encoding='utf-8')
            handles.append(handle)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=HIDDEN)
            processes.append(process)
        wait_http(f'http://127.0.0.1:{api_port}/health', processes[0])
        wait_http(f'http://127.0.0.1:{web_port}', processes[1])
        run([browser_python, '-m', 'tests.profile_chain_browser'], env, 'browser-profile')
        print((ARTIFACT / 'browser-profile.log').read_text(encoding='utf-8')[-1200:], flush=True)
        print('PROFILE_CHAIN_ISOLATED_PASS', flush=True)
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
        if started:
            result = subprocess.run(['docker', 'stop', container], capture_output=True, creationflags=HIDDEN)
            print(f'owned-container-cleanup: exit={result.returncode}', flush=True)


if __name__ == '__main__':
    main()
