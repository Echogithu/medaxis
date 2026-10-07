"""真实数据库、合成本地提取/模型和真实HTTP客户端出站路径。"""
import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_db
from app.main import app

from app.models.agent import CarePlan, PatientHealthProfile
from app.models.patient_report import ReportProcessingJob
from app.models.user import UserRole
from app.services import report_processing as service
from app.services.report_candidates import CandidateError, masked_pages, outgoing_text
from tests.test_patient_care_plans import headers, patient
from tests.test_patient_reports import BASE, create

RECIPIENT = {'provider': 'synthetic', 'model': 'synthetic-model', 'host': 'example.invalid',
    'origin': 'https://example.invalid', 'route_hash': 'synthetic-route'}
CONFIG = {'base_url': 'https://example.invalid/v1', 'api_key': 'synthetic-unused', 'default_model': 'synthetic-model'}
LINE = 'WBC 6.2 10^9/L 3.5-9.5 ↑'
CONTENT = json.dumps({'indicators': [{'name': 'WBC', 'raw_value': '6.2', 'unit': '10^9/L',
    'reference_range': '3.5-9.5', 'abnormal_mark': '↑', 'source_page': 1, 'evidence': LINE}], 'sections': []}, ensure_ascii=False)


@pytest.fixture
async def client(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def fresh_db():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = fresh_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as api:
            yield api
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def processing(monkeypatch, test_engine):
    captured = {'wire': [], 'queue': [], 'local': [], 'recipient': deepcopy(RECIPIENT), 'content': CONTENT}
    async def recipient(_db): return deepcopy(captured['recipient']), deepcopy(CONFIG)
    async def local(content, filename, mime):
        captured['local'].append((content, filename, mime))
        return {'pages': [{'page': 1, 'text': LINE, 'method': 'local_ocr'}]}
    async def transport(request):
        body = json.loads(request.content)
        captured['wire'].append(body)
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'synthetic-model', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': captured['content']}}]})
    monkeypatch.setattr(service, 'recipient_config', recipient)
    monkeypatch.setattr(service, 'extract_report_file', local)
    monkeypatch.setattr(service, 'enqueue_job', lambda job_id: captured['queue'].append(str(job_id)) or True)
    monkeypatch.setattr(service, 'async_session_maker', async_sessionmaker(test_engine, expire_on_commit=False))
    monkeypatch.setattr(service, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(**kwargs,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    return captured


async def setup(client, db):
    user = await patient(db)
    user.full_name, user.phone = '合成患者', '13800000000'
    await db.commit()
    report = await create(client, user)
    return user, report, BASE+'/'+report['id'], headers(user)


async def view(client, url, auth):
    response = await client.get(url+'/workspace', headers=auth)
    assert 200 == response.status_code, response.text
    return response.json()


def version(workspace):
    return {'expected_source_version': workspace['source_version'], 'expected_workflow_revision': workspace['revision']}


async def preview(client, url, auth, pages=None):
    response = await client.post(url+'/preview', headers=auth, json=version(await view(client, url, auth)) | {'pages': pages})
    assert 200 == response.status_code, response.text
    return response.json()['preview']


def consent(preview):
    return {'request_id': str(uuid4()), 'preview_id': preview['id'], 'preview_hash': preview['hash'],
        'expected_source_version': preview['source_version'], 'consent': True, 'ownership_confirmed': True}


@pytest.mark.asyncio
async def test_extract_preview_exact_wire_replay_and_no_other_health_side_effects(client, db_session, test_engine, processing):
    user, report, url, auth = await setup(client, db_session)
    body = version(await view(client, url, auth)) | {'request_id': str(uuid4())}
    first = await client.post(url+'/extract', headers=auth, json=body)
    assert 202 == first.status_code, first.text
    job = first.json()['job']
    repeated = await client.post(url+'/extract', headers=auth, json=body)
    assert job['id'] == repeated.json()['job']['id'] and 1 == len(processing['queue'])
    await service.run_job(job['id'])
    extracted = (await view(client, url, auth))['extract_job']
    assert 'completed' == extracted['status'] and 1 == len(processing['local']) and not processing['wire']
    assert report['files'][0]['id'] == extracted['result']['pages'][0]['file_id']
    p = await preview(client, url, auth)
    assert LINE in p['text'] and 'route_hash' not in p['recipient']
    body = consent(p)
    for changes in [{'consent': False}, {'consent': 1}, {'ownership_confirmed': False}, {'preview_hash': '0'*64}]:
        response = await client.post(url+'/ai', headers=auth, json=body | changes)
        assert response.status_code in [422, 409] and not processing['wire']
    response = await client.post(url+'/ai', headers=auth, json=body)
    assert 202 == response.status_code, response.text
    ai = response.json()['job']
    # 模拟响应丢失后同一UUID重放，不再次投递或外发。
    assert ai['id'] == (await client.post(url+'/ai', headers=auth, json=body)).json()['job']['id']
    await service.run_job(ai['id']); await service.run_job(ai['id'])
    assert 1 == len(processing['wire'])
    wire = processing['wire'][0]
    assert p['text'] == wire['messages'][1]['content']
    assert all(isinstance(message['content'], str) for message in wire['messages'])
    for hidden in [user.full_name, user.email, user.phone, report['id'], report['files'][0]['id'], report['files'][0]['filename'], 'image_url', 'data:image']:
        assert hidden not in json.dumps(wire, ensure_ascii=False)
    workspace = await view(client, url, auth)
    assert 'completed' == workspace['ai_job']['status']
    assert 'unverified' == workspace['ai_job']['result']['review_status']
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(p))).status_code
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        assert [] == (await db.scalars(select(CarePlan).where(CarePlan.patient_id == user.id))).all()
        assert [] == (await db.scalars(select(PatientHealthProfile).where(PatientHealthProfile.patient_id == user.id))).all()


@pytest.mark.asyncio
async def test_editable_preview_stale_model_category_and_profile_changes(client, db_session, processing):
    user, report, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': f'{user.full_name} {user.email} {user.phone}\n报告号：X123\n{LINE}'}])
    assert all(value not in p['text'] for value in [user.full_name, user.email, user.phone, 'X123'])
    assert p['pages'] == masked_pages(p['pages'], user)
    processing['recipient']['model'] = 'changed-model'
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(p))).status_code
    processing['recipient'] = deepcopy(RECIPIENT)
    newer = await preview(client, url, auth, [{'page': 1, 'text': LINE + '\n本人补充'}])
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(p))).status_code
    edit = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
    response = await client.patch(url, headers=auth, json=edit | {'category': 'imaging', 'expected_revision': 0})
    assert 200 == response.status_code, response.text
    assert None is (await view(client, url, auth))['preview']
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(newer))).status_code
    assert not processing['wire']


@pytest.mark.asyncio
async def test_every_workflow_route_requires_owner_and_patient_role(client, db_session, processing):
    owner, _, url, auth = await setup(client, db_session)
    other = await patient(db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p))
    job_id = submitted.json()['job']['id']
    paths = [('get', '/workspace', None), ('post', '/preview', version(await view(client, url, auth))),
        ('post', '/extract', version(await view(client, url, auth)) | {'request_id': str(uuid4())}),
        ('post', '/ai', consent(p)), ('post', '/jobs/'+job_id+'/cancel', None)]
    for method, suffix, data in paths:
        kwargs = {'json': data} if data is not None else {}
        assert 404 == (await getattr(client, method)(url+suffix, headers=headers(other), **kwargs)).status_code
    assert 404 == (await client.post(url+'/jobs/'+str(uuid4())+'/cancel', headers=auth)).status_code
    other.role = UserRole.DOCTOR; await db_session.commit()
    for method, suffix, data in paths:
        kwargs = {'json': data} if data is not None else {}
        assert 403 == (await getattr(client, method)(url+suffix, headers=headers(other), **kwargs)).status_code
    assert not processing['wire']


@pytest.mark.asyncio
async def test_queued_cancel_and_late_response_never_publishes(client, db_session, processing, monkeypatch):
    _, _, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p)); job_id = submitted.json()['job']['id']
    assert 200 == (await client.post(url+'/jobs/'+job_id+'/cancel', headers=auth)).status_code
    await service.run_job(job_id)
    assert not processing['wire']
    p = await preview(client, url, auth)
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p)); job_id = submitted.json()['job']['id']
    started, release = asyncio.Event(), asyncio.Event()
    original = service.send_candidate
    async def slow(*args):
        started.set(); await release.wait()
        return await original(*args)
    monkeypatch.setattr(service, 'send_candidate', slow)
    task = asyncio.create_task(service.run_job(job_id))
    try:
        await asyncio.wait_for(started.wait(), 10)
        cancelled = await client.post(url+'/jobs/'+job_id+'/cancel', headers=auth)
        assert '无法召回' in cancelled.json()['message']
        release.set(); await asyncio.wait_for(task, 10)
    finally:
        release.set()
        if not task.done(): task.cancel()
    job = (await view(client, url, auth))['ai_job']
    assert 'cancelled' == job['status'] and None is job['result']


@pytest.mark.asyncio
async def test_crash_after_dispatch_and_worker_model_change_do_not_resend(client, db_session, test_engine, processing):
    _, _, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p)); job_id = submitted.json()['job']['id']
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        job = await service.load_job(db, job_id)
        job.status, job.dispatch_started_at, job.updated_at = 'processing', service.now(), service.now()-timedelta(minutes=3)
        await db.commit()
    assert job_id in await service.pending_jobs()
    await service.run_job(job_id)
    assert 'delivery_unknown' == (await view(client, url, auth))['ai_job']['error_code']
    assert not processing['wire']
    p = await preview(client, url, auth)
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p)); job_id = submitted.json()['job']['id']
    processing['recipient']['route_hash'] = 'changed-route'
    await service.run_job(job_id)
    assert 'failed' == (await view(client, url, auth))['ai_job']['status'] and not processing['wire']


@pytest.mark.asyncio
async def test_extraction_failure_manual_fallback_and_invalid_response_no_raw_errors(client, db_session, processing, monkeypatch):
    _, _, url, auth = await setup(client, db_session)
    async def broken(*_): raise RuntimeError('合成患者 secret http://private.invalid')
    monkeypatch.setattr(service, 'extract_report_file', broken)
    response = await client.post(url+'/extract', headers=auth, json=version(await view(client, url, auth)) | {'request_id': str(uuid4())})
    await service.run_job(response.json()['job']['id'])
    job = (await view(client, url, auth))['extract_job']
    assert 'failed' == job['status'] and 'secret' not in json.dumps(job, ensure_ascii=False)
    assert not processing['wire']
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    processing['content'] = CONTENT.replace('6.2', '999')
    response = await client.post(url+'/ai', headers=auth, json=consent(p))
    await service.run_job(response.json()['job']['id'])
    job = (await view(client, url, auth))['ai_job']
    assert 'failed' == job['status'] and None is job['result']
    bad = await client.post(url+'/preview', headers=auth, json={'pages': [{'page': 1, 'text': '敏感原文secret'}]})
    assert 422 == bad.status_code and 'secret' not in bad.text


@pytest.mark.asyncio
async def test_real_local_pdf_and_image_pages_without_any_external_call(client, db_session, processing, monkeypatch):
    from app.services.report_files import extract_report_file
    from tests.report_samples import sample_image, text_pdf
    user = await patient(db_session)
    report = await create(client, user, files=[('first.pdf', text_pdf(count=2), 'application/pdf'),
        ('last.png', sample_image(chinese=True), 'image/png')])
    url, auth = BASE+'/'+report['id'], headers(user)
    monkeypatch.setattr(service, 'extract_report_file', extract_report_file)
    response = await client.post(url+'/extract', headers=auth,
        json=version(await view(client, url, auth)) | {'request_id': str(uuid4())})
    await service.run_job(response.json()['job']['id'])
    extracted = (await view(client, url, auth))['extract_job']
    assert 'completed' == extracted['status'], extracted['error_message']
    pages = extracted['result']['pages']
    assert [1, 2, 3] == [page['page'] for page in pages]
    assert [1, 2, 1] == [page['file_page'] for page in pages]
    assert [0, 0, 1] == [page['file_position'] for page in pages]
    assert '6.2' in pages[2]['text'] and not processing['wire']


@pytest.mark.asyncio
async def test_expired_preview_source_change_and_identity_update_invalidate(client, db_session, test_engine, processing):
    user, _, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE+'\n之后成为账号姓名'}])
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        user_row = await db.get(type(user), user.id)
        user_row.full_name = '之后成为账号姓名'; await db.commit()
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(p))).status_code
    p = await preview(client, url, auth)
    async with factory() as db:
        report = await service.workspace_report(db, UUID(url.split('/')[-1]), lock=True)
        changed = deepcopy(report.workflow)
        changed['preview']['expires_at'] = (service.now()-timedelta(seconds=1)).isoformat()
        report.workflow = changed; await db.commit()
    assert 409 == (await client.post(url+'/ai', headers=auth, json=consent(p))).status_code
    p = await preview(client, url, auth)
    response = await client.post(url+'/ai', headers=auth, json=consent(p))
    async with factory() as db:
        report = await service.workspace_report(db, UUID(url.split('/')[-1]), lock=True)
        report.source_version += 1; await db.commit()
    await service.run_job(response.json()['job']['id'])
    assert 'cancelled' == (await view(client, url, auth))['ai_job']['status'] and not processing['wire']


@pytest.mark.asyncio
async def test_concurrent_ai_submission_sends_once_and_list_has_metadata_only(client, db_session, processing):
    user, _, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    body = consent(p)
    responses = await asyncio.gather(*[client.post(url+'/ai', headers=auth, json=body) for _ in range(2)])
    assert [202, 202] == [response.status_code for response in responses]
    assert responses[0].json()['job']['id'] == responses[1].json()['job']['id']
    assert 1 == len(processing['queue'])
    await service.run_job(responses[0].json()['job']['id'])
    listing = (await client.get(BASE, headers=headers(user))).json()['items'][0]
    assert 'completed' == listing['ai_status']
    assert not {'workflow', 'preview', 'input', 'result', 'pages', 'text'} & set(listing)
    assert 1 == len(processing['wire'])


@pytest.mark.asyncio
async def test_category_change_back_does_not_resurrect_old_ai_and_foreign_job_cancel_is_scoped(client, db_session, processing):
    owner, report, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    response = await client.post(url+'/ai', headers=auth, json=consent(p))
    job_id = response.json()['job']['id']
    await service.run_job(job_id)
    other, _, other_url, other_auth = await setup(client, db_session)
    assert owner.id != other.id
    assert 404 == (await client.post(other_url+'/jobs/'+job_id+'/cancel', headers=other_auth)).status_code
    assert 'completed' == (await view(client, url, auth))['ai_job']['status']
    fields = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
    for revision, category in enumerate(['imaging', 'lab']):
        edited = await client.patch(url, headers=auth, json=fields | {'category': category, 'expected_revision': revision})
        assert 200 == edited.status_code, edited.text
    listing = (await client.get(BASE, headers=auth)).json()['items'][0]
    assert 'not_started' == listing['ai_status']
    assert None is (await view(client, url, auth))['ai_job']
