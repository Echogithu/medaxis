"""复用隔离工具运行随访真实数据库与浏览器门禁，绝不指向业务库。"""
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
ARTIFACT = ROOT / '.ai/tasks/2026-10-03-health-followup-workspace/followup'


def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    harness.ARTIFACT = ARTIFACT
    suffix = uuid4().hex[:10]
    container = f'medaxis-followup-test-{suffix}'
    database, demo = f'medaxis_test_followup_{suffix}', f'medaxis_demo_e2e_followup_{suffix}'
    port, api_port, web_port = harness.free_port(), harness.free_port(), harness.free_port()
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), PYTHONUTF8='1',
        SECRET_KEY=secrets.token_hex(32), API_KEY_MASTER_KEY=secrets.token_hex(32),
        MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', ENVIRONMENT='staging', DEFAULT_ADMIN_PASSWORD='',
        MEDAXIS_DEMO_REDIS_MODE='substitute', REDIS_URL='redis://127.0.0.1:6399/0', DEMO_API_PORT=str(api_port))
    def point(db):
        url=f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{db}"
        for key in ['DATABASE_URL','ASYNC_DATABASE_URL','TEST_DATABASE_URL']: env[key]=url
    processes, handles, started = [], [], False
    try:
        harness.run(['docker','run','--rm','-d','--pull','never','--name',container,'-p',f'127.0.0.1:{port}:5432',
                     '-e','POSTGRES_PASSWORD','-e',f'POSTGRES_DB={database}','pgvector/pgvector:pg17'],env,'container-start')
        started=True
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(port,env['POSTGRES_PASSWORD'],database,lambda c:c.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt==99: raise
                time.sleep(.2)
        point(database)
        harness.run([sys.executable,'-m','alembic','upgrade','head'],env,'migration-followup')
        if '--browser-only' not in sys.argv:
            harness.run([sys.executable,'-m','pytest','-p','no:cacheprovider','-q','--tb=short',
                'tests/test_patient_care_plans.py','tests/test_patient_profile_api.py',
                'tests/test_patient_reminders.py','tests/test_monitoring_reminder_retry.py'],env,'pytest-followup')
            print((ARTIFACT/'pytest-followup.log').read_text(encoding='utf-8')[-1100:],flush=True)
        if '--api-only' in sys.argv:
            print('FOLLOWUP_API_ISOLATED_PASS',flush=True)
            return
        asyncio.run(harness.sql(port,env['POSTGRES_PASSWORD'],database,lambda c:c.execute(f'CREATE DATABASE "{demo}"')))
        point(demo)
        harness.run([sys.executable,'-m','alembic','upgrade','head'],env,'migration-browser')
        os.environ.update(env)
        async def seed():
            from app.core.security import create_access_token
            from app.db.session import async_session_maker, async_engine
            from app.models.user import User, UserRole, UserStatus
            from app.models.medical_case import MedicalCase
            async with async_session_maker() as db:
                user=User(email=f'followup-browser-{suffix}@example.com', full_name='随访合成患者',
                          role=UserRole.PATIENT,status=UserStatus.ACTIVE,hashed_password='unused')
                db.add(user)
                await db.flush()
                db.add(MedicalCase(patient_id=user.id,title='浏览器随访来源病历'))
                await db.commit()
                token=create_access_token(str(user.id),platform='web')
            await async_engine.dispose()
            return token
        env['FOLLOWUP_BROWSER_TOKEN']=asyncio.run(seed())
        env.update(FOLLOWUP_API_URL=f'http://127.0.0.1:{api_port}',FOLLOWUP_WEB_URL=f'http://127.0.0.1:{web_port}')
        for command,cwd,log in [
            ([sys.executable,'-m','tests.patient_demo_server'],BACKEND,'followup-api.log'),
            (['node',str(ROOT/'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',str(web_port),'--strictPort'],ROOT/'frontend','followup-vite.log')]:
            handle=(ARTIFACT/log).open('w',encoding='utf-8'); handles.append(handle)
            processes.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=handle,stderr=subprocess.STDOUT,creationflags=harness.HIDDEN))
        harness.wait_http(f'http://127.0.0.1:{api_port}/health',processes[0])
        harness.wait_http(f'http://127.0.0.1:{web_port}',processes[1])
        browser_python=os.getenv('PROFILE_BROWSER_PYTHON') or shutil.which('python') or sys.executable
        harness.run([browser_python,'-m','tests.followup_chain_browser'],env,'browser-followup')
        print((ARTIFACT/'browser-followup.log').read_text(encoding='utf-8')[-1500:],flush=True)
        print('FOLLOWUP_CHAIN_ISOLATED_PASS',flush=True)
    finally:
        for process in reversed(processes):
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
        if started:
            result=subprocess.run(['docker','stop',container],capture_output=True,creationflags=harness.HIDDEN)
            print(f'owned-container-cleanup: exit={result.returncode}',flush=True)


if __name__=='__main__': main()
