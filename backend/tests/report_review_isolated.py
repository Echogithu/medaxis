"""T4只创建随机合成数据库；迁移保护、API及可选Edge核对流程。"""
import asyncio
import json
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

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT/'backend'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    suffix = uuid4().hex[:10]
    artifact = ROOT/'.ai/tasks/2026-10-03-patient-reports/artifacts/t4/runs'/suffix
    artifact.mkdir(parents=True, exist_ok=True); harness.ARTIFACT = artifact
    print(f'review-artifact: {artifact}', flush=True)
    container, database = f'medaxis-review-test-{suffix}', f'medaxis_test_review_{suffix}'
    demo = f'medaxis_demo_e2e_review_{suffix}'
    port, api_port, web_port = [harness.free_port() for _ in range(3)]
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), SECRET_KEY=secrets.token_hex(32),
        API_KEY_MASTER_KEY=secrets.token_hex(32), PYTHONUTF8='1', ENVIRONMENT='staging', DEFAULT_ADMIN_PASSWORD='',
        MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1', DEMO_REDIS_LOCK_MODE='substitute', SENTRY_DSN='', DEBUG='false',
        REDIS_URL='redis://127.0.0.1:6399/0', CELERY_BROKER_URL='redis://127.0.0.1:6399/1',
        CELERY_RESULT_BACKEND='redis://127.0.0.1:6399/2', DEMO_API_PORT=str(api_port), REPORTS_REVIEW_ARTIFACT=str(artifact))
    def point(db):
        url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{db}"
        env.update(DATABASE_URL=url, ASYNC_DATABASE_URL=url, TEST_DATABASE_URL=url)
    processes, handles, started = [], [], False
    try:
        harness.run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container,
            '-p', f'127.0.0.1:{port}:5432', '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}',
            'pgvector/pgvector:pg17'], env, 'container-start')
        started = True
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda db: db.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99: raise
                time.sleep(.2)
        point(database)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', '9b4e8a2d0f31'], env, 'migration-before')
        patient_id, report_id = uuid4(), uuid4()
        async def legacy(db):
            await db.execute("""INSERT INTO users(id,email,full_name,role,status,is_verified,created_at,updated_at)
                VALUES($1,$2,'合成旧报告患者','PATIENT','ACTIVE',false,now(),now())""", patient_id, f'{suffix}@example.invalid')
            await db.execute("""INSERT INTO patient_reports(id,patient_id,request_id,request_fingerprint,content_hash,
                title,category,institution,notes,ownership_declared,revision,source_version,workflow,created_at,updated_at)
                VALUES($1,$2,$3,$4,$4,'既有合成报告','lab','','',true,0,1,'{}'::jsonb,now(),now())""", report_id, patient_id, uuid4(), '0'*64)
            await db.execute("""INSERT INTO patient_report_files(id,report_id,position,filename,mime_type,byte_size,page_count,sha256,content)
                VALUES($1,$2,0,'synthetic.txt','image/png',3,1,$3,$4)""", uuid4(), report_id, '0'*64, b'old')
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, legacy))
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-upgrade')
        harness.run([sys.executable, '-m', 'alembic', 'downgrade', '9b4e8a2d0f31'], env, 'migration-empty-downgrade')
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-reupgrade')
        async def preserved(db):
            assert b'old' == await db.fetchval('SELECT content FROM patient_report_files WHERE report_id=$1', report_id)
            assert '{}' == await db.fetchval('SELECT workflow::text FROM patient_reports WHERE id=$1', report_id)
            await db.execute("UPDATE patient_reports SET review_state='{\"epoch\":1}'::jsonb WHERE id=$1", report_id)
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, preserved))
        refused = subprocess.run([sys.executable, '-m', 'alembic', 'downgrade', '9b4e8a2d0f31'], env=env,
            cwd=BACKEND, capture_output=True, text=True, encoding='utf-8', creationflags=harness.HIDDEN)
        assert refused.returncode != 0 and '禁止直接丢弃患者草稿' in refused.stderr
        (artifact/'migration-guard.log').write_text('Original bytes and workspace preserved; nonempty review downgrade refused.\n', encoding='utf-8')
        if '--browser-only' not in sys.argv:
            tests = [] if '--regression-only' in sys.argv else ['tests/test_report_review.py']
            if '--targeted' not in sys.argv: tests.extend(['tests/test_patient_reports.py', 'tests/test_report_processing.py'])
            harness.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '--tb=short', *tests], env, 'pytest-review')
            print((artifact/'pytest-review.log').read_text(encoding='utf-8')[-2000:], flush=True)
        if '--api-only' in sys.argv:
            print('REPORT_REVIEW_API_ISOLATED_PASS', flush=True); return
        asyncio.run(harness.sql(port, env['POSTGRES_PASSWORD'], database, lambda db: db.execute(f'CREATE DATABASE "{demo}"')))
        point(demo); harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration-browser')
        from tests.database_safety import validate_demo_database
        validate_demo_database(env['DATABASE_URL']); os.environ.update(env)
        async def seed():
            from app.core.security import create_access_token
            from app.db.session import async_session_maker, async_engine
            from app.models.user import User, UserRole, UserStatus
            async with async_session_maker() as db:
                user = User(email=f'review-browser-{uuid4()}@example.invalid', full_name='人工核对合成患者',
                    role=UserRole.PATIENT, status=UserStatus.ACTIVE, hashed_password='unused')
                db.add(user); await db.commit(); token = create_access_token(str(user.id), platform='web')
            await async_engine.dispose()
            return token
        env['REPORTS_BROWSER_TOKEN'] = asyncio.run(seed())
        env.update(REPORTS_API_URL=f'http://127.0.0.1:{api_port}', REPORTS_WEB_URL=f'http://127.0.0.1:{web_port}')
        from tests.report_samples import sample_image
        (artifact/'synthetic-report.png').write_bytes(sample_image(chinese=True))
        for command, cwd, name in [
            ([sys.executable, '-m', 'tests.patient_demo_server'], BACKEND, 'api.log'),
            (['node', str(ROOT/'frontend/tests/patientReportsDevServer.mjs')], ROOT/'frontend', 'vite.log')]:
            handle = (artifact/name).open('w', encoding='utf-8'); handles.append(handle)
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle,
                stderr=subprocess.STDOUT, creationflags=harness.HIDDEN))
        harness.wait_http(env['REPORTS_API_URL']+'/health', processes[0]); harness.wait_http(env['REPORTS_WEB_URL'], processes[1])
        # AI候选是预置的合成完成结果，不调用外部模型；核对API/UI保持真实。
        import httpx
        with httpx.Client(base_url=env['REPORTS_API_URL'], headers={'Authorization': 'Bearer '+env['REPORTS_BROWSER_TOKEN']}, timeout=60) as api:
            response = api.post('/api/v1/patient/reports', data={'metadata': json.dumps({
                'title': '合成AI候选核对报告', 'category': 'lab', 'ownership_declared': True, 'request_id': str(uuid4())})},
                files={'files': ('synthetic-report.png', (artifact/'synthetic-report.png').read_bytes(), 'image/png')})
            assert response.status_code == 201
            env['REPORTS_CANDIDATE_REPORT_ID'] = response.json()['id']
            base = '/api/v1/patient/reports/'+response.json()['id']
            workflow = api.get(base+'/workspace').json()
            preview = api.post(base+'/preview', json={'expected_source_version': workflow['source_version'],
                'expected_workflow_revision': workflow['revision'], 'pages': [{'page': 1, 'text': 'WBC 6.2 10^9/L'}]})
            assert preview.status_code == 200
        async def candidate():
            from uuid import UUID
            from app.db.session import async_session_maker, async_engine
            from app.models.patient_report import ReportProcessingJob
            from app.services.report_processing import workspace_report, source_hash, update_state
            async with async_session_maker() as db:
                report = await workspace_report(db, UUID(env['REPORTS_CANDIDATE_REPORT_ID']), lock=True)
                job = ReportProcessingJob(report_id=report.id, request_id=uuid4(), request_fingerprint='0'*64,
                    kind='ai', status='completed', source_version=report.source_version, source_hash=source_hash(report, 'ai'), input={},
                    result={'indicators': [{'name': 'WBC', 'raw_value': '6.2', 'unit': '10^9/L', 'reference_range': None,
                        'abnormal_mark': None, 'source_page': 1, 'evidence': 'WBC 6.2 10^9/L'}], 'sections': [],
                        'preview_hash': report.workflow['preview']['hash'], 'review_status': 'unverified'})
                db.add(job); await db.flush(); update_state(report, ai_id=str(job.id)); await db.commit()
            await async_engine.dispose()
        asyncio.run(candidate())
        browser_python = os.getenv('PROFILE_BROWSER_PYTHON') or shutil.which('python') or sys.executable
        harness.run([browser_python, '-m', 'tests.report_review_browser'], env, 'browser')
        print((artifact/'browser.log').read_text(encoding='utf-8')[-2500:], flush=True)
        print('REPORT_REVIEW_CHAIN_ISOLATED_PASS', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is not None: continue
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
        if started:
            result = subprocess.run(['docker', 'stop', container], capture_output=True, creationflags=harness.HIDDEN)
            print(f'owned-review-container-cleanup: exit={result.returncode}', flush=True)


if __name__ == '__main__': main()
