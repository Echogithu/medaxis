"""真实 Redis/Celery/Edge + 本机合成模型 HTTP；只操作本次新建的隔离资源。"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

import asyncpg
from tests import profile_chain_isolated as harness

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
LINE = 'WBC 6.2 10^9/L 3.5-9.5 ↑'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    suffix = uuid4().hex[:10]
    artifact = ROOT / '.ai/tasks/2026-10-03-patient-reports/artifacts/t3/browser-runs' / suffix
    artifact.mkdir(parents=True, exist_ok=True)
    harness.ARTIFACT = artifact
    print(f'workflow-chain-artifact: {artifact}', flush=True)
    pg, redis = f'medaxis-report-chain-pg-{suffix}', f'medaxis-report-chain-redis-{suffix}'
    database = f'medaxis_demo_e2e_reports_{suffix}'
    pg_port, redis_port, api_port, web_port = [harness.free_port() for _ in range(4)]
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(24), SECRET_KEY=secrets.token_hex(32),
        API_KEY_MASTER_KEY=secrets.token_hex(32), PYTHONUTF8='1', ENVIRONMENT='staging',
        DEFAULT_ADMIN_PASSWORD='', DEBUG='false', SENTRY_DSN='', DEMO_REDIS_LOCK_MODE='redis',
        CELERY_TASK_ALWAYS_EAGER='false', DEMO_API_PORT=str(api_port),
        REDIS_URL=f'redis://127.0.0.1:{redis_port}/0', CELERY_BROKER_URL=f'redis://127.0.0.1:{redis_port}/1',
        CELERY_RESULT_BACKEND=f'redis://127.0.0.1:{redis_port}/2',
        REPORTS_API_URL=f'http://127.0.0.1:{api_port}', REPORTS_WEB_URL=f'http://127.0.0.1:{web_port}',
        REPORTS_WORKFLOW_ARTIFACT=str(artifact), REPORTS_CONTROL_TOKEN=secrets.token_hex(24))
    url = f"postgresql+asyncpg://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{pg_port}/{database}"
    env.update(DATABASE_URL=url, ASYNC_DATABASE_URL=url, TEST_DATABASE_URL=url)
    processes, handles, containers, wire = [], [], [], []
    state = {'worker': None, 'worker_count': 0}
    lock = threading.Lock()

    def launch(command, cwd, name):
        handle = (artifact / name).open('w', encoding='utf-8'); handles.append(handle)
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle,
            stderr=subprocess.STDOUT, creationflags=harness.HIDDEN)
        processes.append(process)
        return process

    def worker(action):
        with lock:
            current = state['worker']
            if action == 'stop' and current and current.poll() is None:
                current.terminate()
                try: current.wait(timeout=10)
                except subprocess.TimeoutExpired: current.kill(); current.wait(timeout=5)
            elif action == 'start' and (not current or current.poll() is not None):
                state['worker_count'] += 1
                state['worker'] = launch([sys.executable, '-m', 'celery', '-A', 'app.tasks.celery_app:celery_app',
                    'worker', '--pool=solo', '--concurrency=1', '--loglevel=warning',
                    '--without-gossip', '--without-mingle', '--without-heartbeat'], BACKEND,
                    f"worker-{state['worker_count']}.log")
            return {'worker_starts': state['worker_count']}

    class SyntheticModel(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def respond(self, value, status=200):
            payload = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload))); self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path != '/test/wire' or self.headers.get('X-Test-Control') != env['REPORTS_CONTROL_TOKEN']:
                return self.respond({'error': 'unknown'}, 404)
            with lock: captured = list(wire)
            self.respond(captured)

        def do_POST(self):
            if self.path.startswith('/test/worker/'):
                if self.headers.get('X-Test-Control') != env['REPORTS_CONTROL_TOKEN']:
                    return self.respond({'error': 'unknown'}, 404)
                action = self.path.rsplit('/', 1)[1]
                if action not in {'start', 'stop'}: return self.respond({'error': 'unknown'}, 404)
                return self.respond(worker(action))
            if self.path != '/v1/chat/completions': return self.respond({'error': 'unknown'}, 404)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 300000: return self.respond({'error': 'size'}, 400)
            body = json.loads(self.rfile.read(length))
            with lock: wire.append(body)
            text = body['messages'][-1]['content']
            time.sleep(3 if any(marker in text for marker in ['CANCEL_TEST', 'CRASH_TEST']) else 1)
            result = {'indicators': [{'name': 'WBC', 'raw_value': '6.2', 'unit': '10^9/L',
                'reference_range': '3.5-9.5', 'abnormal_mark': '↑', 'source_page': 1, 'evidence': LINE}], 'sections': []}
            self.respond({'id': 'synthetic-local', 'object': 'chat.completion', 'created': 1,
                'model': 'synthetic-report-model', 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': json.dumps(result, ensure_ascii=False)}}]})

    server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticModel)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    env['REPORTS_MODEL_URL'] = f'http://127.0.0.1:{server.server_port}'
    try:
        for container, args in [
            (pg, ['-p', f'127.0.0.1:{pg_port}:5432', '-e', 'POSTGRES_PASSWORD', '-e', f'POSTGRES_DB={database}', 'pgvector/pgvector:pg17']),
            (redis, ['-p', f'127.0.0.1:{redis_port}:6379', 'redis:7-alpine'])]:
            harness.run(['docker', 'run', '--rm', '-d', '--pull', 'never', '--name', container, *args], env, container)
            containers.append(container)
        for attempt in range(100):
            try:
                asyncio.run(harness.sql(pg_port, env['POSTGRES_PASSWORD'], database, lambda db: db.fetchval('SELECT 1')))
                break
            except (OSError, asyncpg.PostgresError):
                if attempt == 99: raise
                time.sleep(.2)
        harness.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env, 'migration')
        from tests.database_safety import validate_demo_database
        validate_demo_database(url)
        os.environ.update(env)

        async def seed():
            from app.core.encryption import encrypt_value
            from app.core.security import create_access_token
            from app.db.session import async_session_maker, async_engine
            from app.models.config import LLMProviderConfig
            from app.models.user import User, UserRole, UserStatus
            async with async_session_maker() as db:
                tokens = []
                for label in ['本人', '他人']:
                    user = User(email=f'report-workflow-{uuid4()}@example.invalid', full_name=f'合成患者{label}',
                        phone='13800000000' if label == '本人' else '13900000000',
                        role=UserRole.PATIENT, status=UserStatus.ACTIVE, hashed_password='unused')
                    db.add(user); await db.flush()
                    tokens.append(create_access_token(str(user.id), platform='web'))
                db.add(LLMProviderConfig(provider='synthetic-report', platform='web', name='本机合成验收模型',
                    base_url=env['REPORTS_MODEL_URL']+'/v1', api_key_encrypted=encrypt_value(secrets.token_hex(24)),
                    default_model='synthetic-report-model', model_type='diagnosis', is_default=True, is_active=True))
                await db.commit()
            await async_engine.dispose()
            return tokens
        env['REPORTS_BROWSER_TOKEN'], env['REPORTS_OTHER_TOKEN'] = asyncio.run(seed())
        from tests.report_samples import sample_image, text_pdf
        (artifact/'synthetic-two-pages.pdf').write_bytes(text_pdf(count=2))
        (artifact/'synthetic-image.png').write_bytes(sample_image(chinese=True))
        api_process = launch([sys.executable, '-m', 'tests.patient_demo_server'], BACKEND, 'api.log')
        vite_process = launch(['node', str(ROOT/'frontend/tests/patientReportsDevServer.mjs')], ROOT/'frontend', 'vite.log')
        harness.wait_http(env['REPORTS_API_URL']+'/health', api_process)
        harness.wait_http(env['REPORTS_WEB_URL'], vite_process)
        browser_python = os.getenv('PROFILE_BROWSER_PYTHON') or shutil.which('python') or sys.executable
        harness.run([browser_python, '-m', 'tests.report_workflow_chain_browser'], env, 'browser')
        print((artifact/'browser.log').read_text(encoding='utf-8')[-3000:], flush=True)
        assert state['worker_count'] >= 2
        # 丢失 broker 消息后，真实 Celery 扫描任务重新投递数据库中的 queued 任务。
        import httpx
        with httpx.Client(base_url=env['REPORTS_API_URL'], headers={'Authorization': 'Bearer '+env['REPORTS_BROWSER_TOKEN']}, timeout=30) as api:
            report_id = json.loads((artifact/'browser-result.json').read_text(encoding='utf-8'))['report_id']
            base = f'/api/v1/patient/reports/{report_id}'
            worker('stop')
            workspace = api.get(base+'/workspace').json()
            created = api.post(base+'/extract', json={'request_id': str(uuid4()),
                'expected_source_version': workspace['source_version'], 'expected_workflow_revision': workspace['revision']})
            assert created.status_code == 202, created.status_code
            from redis import Redis
            broker = Redis.from_url(env['CELERY_BROKER_URL'])
            assert broker.llen('celery') > 0
            broker.delete('celery')  # 仅本次创建、独占的 Redis 数据库，模拟消息丢失。
            assert api.get(base+'/workspace').json()['extract_job']['status'] == 'queued'
            from app.tasks.reports import scan_pending_report_jobs
            scan_pending_report_jobs.apply_async(retry=False)
            worker('start')
            for _ in range(120):
                job = api.get(base+'/workspace').json()['extract_job']
                if job['status'] in {'completed', 'failed'}: break
                time.sleep(.5)
            assert job['status'] == 'completed', job['status']
            assert len(job['result']['pages']) == 3
            # 外发后中断自己的worker。仅推进该合成任务的时间，覆盖租约过期分支。
            workspace = api.get(base+'/workspace').json()
            response = api.post(base+'/preview', json={'expected_source_version': workspace['source_version'],
                'expected_workflow_revision': workspace['revision'], 'pages': [
                    {'page': 1, 'text': LINE+'\nCRASH_TEST'}, {'page': 2, 'text': ''}, {'page': 3, 'text': ''}]})
            assert response.status_code == 200
            preview = response.json()['preview']
            created = api.post(base+'/ai', json={'request_id': str(uuid4()), 'preview_id': preview['id'],
                'preview_hash': preview['hash'], 'expected_source_version': preview['source_version'],
                'consent': True, 'ownership_confirmed': True})
            assert created.status_code == 202
            interrupted_id = created.json()['job']['id']
            for _ in range(100):
                with lock: count = len(wire)
                if count == 3: break
                time.sleep(.1)
            assert count == 3
            worker('stop')
            assert api.get(base+'/workspace').json()['ai_job']['status'] == 'processing'
            from uuid import UUID
            asyncio.run(harness.sql(pg_port, env['POSTGRES_PASSWORD'], database,
                lambda db: db.execute("UPDATE patient_report_jobs SET updated_at=now()-interval '3 minutes' WHERE id=$1", UUID(interrupted_id))))
            scan_pending_report_jobs.apply_async(retry=False)
            worker('start')
            for _ in range(120):
                job = api.get(base+'/workspace').json()['ai_job']
                if job['status'] == 'failed': break
                time.sleep(.5)
            assert job['error_code'] == 'delivery_unknown' and job['result'] is None
            time.sleep(4)
            with lock: assert len(wire) == 3
            # 最后用真实beat分钟计划补投，不能把手动调用scanner冒充周期调度。
            worker('stop')
            workspace = api.get(base+'/workspace').json()
            created = api.post(base+'/extract', json={'request_id': str(uuid4()),
                'expected_source_version': workspace['source_version'], 'expected_workflow_revision': workspace['revision']})
            assert created.status_code == 202
            assert broker.llen('celery') > 0
            broker.delete('celery')
            launch([sys.executable, '-m', 'celery', '-A', 'app.tasks.celery_app:celery_app', 'beat',
                '--loglevel=info', '--max-interval=1', '--schedule='+str(artifact/'synthetic-beat')], BACKEND, 'beat.log')
            worker('start')
            for _ in range(240):
                job = api.get(base+'/workspace').json()['extract_job']
                if job['status'] in {'completed', 'failed'}: break
                time.sleep(.5)
            assert job['status'] == 'completed', job['status']
        (artifact/'queue-result.json').write_text(json.dumps({'real_redis': True, 'real_celery': True,
            'worker_starts': state['worker_count'], 'lost_message_sweep_completed': True,
            'real_periodic_beat_completed': True, 'worker_interrupted_after_dispatch_no_resend': True,
            'stale_lease_clock': 'isolated job timestamp advanced by 3 minutes',
            'model_http_calls': len(wire)}, indent=2), encoding='utf-8')
        print('REPORT_WORKFLOW_REAL_QUEUE_BROWSER_PASS', flush=True)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        for process in reversed(processes):
            if process.poll() is not None: continue
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        for handle in handles: handle.close()
        for container in reversed(containers):
            result = subprocess.run(['docker', 'stop', container], capture_output=True, creationflags=harness.HIDDEN)
            print(f'owned-chain-container-cleanup: {container} exit={result.returncode}', flush=True)


if __name__ == '__main__': main()
