"""真实DB生命周期：恢复不授权、彻底删除不复活、晚到结果不发布。"""
import asyncio
import json
from datetime import timedelta
from uuid import UUID, uuid4
import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.agent import CarePlan, MonitoringEvent
from app.models.patient_report import PatientReport, PatientReportFile, ReportCaseLink, ReportLifecycleSubmission, ReportManagementOperation, ReportProcessingJob, ReportReviewVersion, ReportUploadSubmission
from app.models.user import UserRole
from app.services import report_processing as processing_service
from tests.test_patient_care_plans import headers, patient
from tests.test_patient_reports import BASE, create, metadata, multipart
from tests.test_report_processing import client, processing, setup, preview, consent, view as workflow_view, version as workflow_version, LINE, CONTENT
from tests.test_report_review import save as save_review, confirm as confirm_review
from tests.test_report_links import case, state as links_state, body as links_body, save as save_links


async def management(api, url, auth):
    response = await api.get(url+'/lifecycle', headers=auth)
    assert 200 == response.status_code, response.text
    return response.json()


def request(view, kind, **changes):
    return {'request_id': str(uuid4()), 'expected_state_token': view['state_token']} | (
        {'confirmed_permanent_delete': True} if kind == 'purge' else {}) | changes


async def act(api, url, auth, kind, data=None):
    data = data or request(await management(api, url, auth), kind)
    response = await api.post(url+'/lifecycle/'+kind, headers=auth, json=data)
    assert 200 == response.status_code, response.text
    return response.json(), data


@pytest.mark.asyncio
async def test_trash_restore_history_links_all_pending_and_treatment_untouched(client, db_session, test_engine, processing):
    user, report, url, auth = await setup(client, db_session)
    original = (await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)).content
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    await save_review(client, url, auth); await confirm_review(client, url, auth)
    before_history = (await client.get(url+'/review/history', headers=auth)).json()
    linked_case = await case(db_session, user)
    await save_links(client, url, auth, links_body(await links_state(client, url, auth), [linked_case.id]))
    submitted = await client.post(url+'/ai', headers=auth, json=consent(p)); assert 202 == submitted.status_code
    job_id = submitted.json()['job']['id']
    row = await db_session.get(PatientReport, UUID(report['id']))
    stray = ReportProcessingJob(report_id=row.id, request_id=uuid4(), request_fingerprint='0'*64, kind='extract',
        source_version=row.source_version, source_hash=processing_service.source_hash(row, 'extract'), status='queued', input={}, result={})
    plan = CarePlan(patient_id=user.id, title='合成既有随访及用药', status='active', tasks={'tasks': [{'id': 'med', 'type': 'medication', 'status': 'pending'}]})
    db_session.add_all([stray, plan]); await db_session.flush()
    reminder = MonitoringEvent(patient_id=user.id, plan_id=plan.id, event_type='medication_reminder', scheduled_at=processing_service.now()+timedelta(days=1), status='pending')
    db_session.add(reminder); await db_session.commit()
    state = await management(client, url, auth)
    assert 1 == state['links_count'] and 2 == state['pending_jobs']
    trashed, trash_body = await act(client, url, auth, 'trash', request(state, 'trash'))
    assert 'trash' == trashed['workspace']['report']['archive_status']
    assert 0 == trashed['workspace']['links_count'] == trashed['workspace']['pending_jobs']
    active = (await client.get(BASE, headers=auth)).json(); recycle = (await client.get(BASE, headers=auth, params={'archive': 'trash'})).json()
    assert 0 == active['total'] and 1 == active['stats']['trashed'] and 0 == active['stats']['archived']
    assert [report['id']] == [item['id'] for item in recycle['items']]
    assert 0 == (await client.get('/api/v1/patient/cases/'+str(linked_case.id)+'/reports', headers=auth)).json()['total']
    for identifier in [job_id, str(stray.id)]:
        assert identifier not in await processing_service.pending_jobs()
        await processing_service.run_job(identifier)
    restored, restore_body = await act(client, url, auth, 'restore')
    assert 'archived' == restored['workspace']['report']['archive_status']
    workspace = await workflow_view(client, url, auth)
    assert workspace['preview'] is None and workspace['ai_job'] is None and workspace['extract_job'] is None
    assert before_history == (await client.get(url+'/review/history', headers=auth)).json()
    assert 'patient_confirmed' == (await client.get(url+'/review', headers=auth)).json()['review_status']
    assert original == (await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)).content
    assert [] == (await links_state(client, url, auth))['items']
    # 重放旧移除只返回当前状态，不把刚恢复报告重新移除。
    replay = await client.post(url+'/lifecycle/trash', headers=auth, json=trash_body)
    assert 'archived' == replay.json()['workspace']['report']['archive_status']
    await act(client, url, auth, 'trash'); await act(client, url, auth, 'purge')
    assert 404 == (await client.get(url+'/lifecycle', headers=auth)).status_code
    assert not processing['wire'] and not processing['local']
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        assert 'active' == (await db.get(CarePlan, plan.id)).status
        assert plan.tasks == (await db.get(CarePlan, plan.id)).tasks
        assert 'pending' == (await db.get(MonitoringEvent, reminder.id)).status
        for model in [PatientReportFile, ReportProcessingJob, ReportReviewVersion, ReportCaseLink, ReportManagementOperation]:
            assert 0 == await db.scalar(select(func.count()).select_from(model).where(model.report_id == row.id))
        assert [] == (await db.scalars(select(ReportUploadSubmission).where(ReportUploadSubmission.patient_id == user.id, ReportUploadSubmission.report_id.is_not(None)))).all()


@pytest.mark.asyncio
async def test_trashed_routes_and_foreign_doctor_permissions(client, db_session, processing):
    user, report, url, auth = await setup(client, db_session)
    other = await patient(db_session)
    state = await management(client, url, auth)
    for kind in ['trash', 'restore', 'purge']:
        assert 404 == (await client.post(url+'/lifecycle/'+kind, headers=headers(other), json=request(state, kind))).status_code
    assert 404 == (await client.get(url+'/lifecycle', headers=headers(other))).status_code
    assert [] == (await client.get(BASE, headers=headers(other), params={'archive': 'trash'})).json()['items']
    assert 401 == (await client.get(url+'/lifecycle')).status_code
    other.role = UserRole.DOCTOR; await db_session.commit()
    assert 403 == (await client.get(url+'/lifecycle', headers=headers(other))).status_code
    for kind in ['trash', 'restore', 'purge']:
        assert 403 == (await client.post(url+'/lifecycle/'+kind, headers=headers(other), json=request(state, kind))).status_code
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    ai = await client.post(url+'/ai', headers=auth, json=consent(p)); assert 202 == ai.status_code
    await act(client, url, auth, 'trash')
    paths = [('get', '', 410), ('get', '/files/'+report['files'][0]['id'], 410), ('get', '/workspace', 404),
        ('get', '/review', 404), ('get', '/review/history', 404), ('get', '/case-options', 410), ('get', '/case-links', 410)]
    for method, suffix, expected in paths:
        assert expected == (await getattr(client, method)(url+suffix, headers=auth)).status_code
    for suffix, body in [('/ai', consent(p)), ('/extract', {'request_id': str(uuid4()), 'expected_source_version': 1, 'expected_workflow_revision': 0}),
                         ('/preview', {}), ('/review/drafts', {}), ('/review/confirm', {}), ('/case-links', {}), ('/jobs/'+ai.json()['job']['id']+'/cancel', {})]:
        assert (await client.post(url+suffix, headers=auth, json=body)).status_code in [404, 410]
    edit = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
    assert 410 == (await client.patch(url, headers=auth, json=edit | {'expected_revision': report['revision']})).status_code
    assert not processing['wire']


@pytest.mark.asyncio
async def test_uuid_concurrency_replay_purge_tombstones_and_conflicts(client, db_session, processing):
    user = await patient(db_session); data = metadata()
    report = await create(client, user, data); url, auth = BASE+'/'+report['id'], headers(user)
    state = await management(client, url, auth); body = request(state, 'trash')
    responses = await asyncio.gather(*(client.post(url+'/lifecycle/trash', headers=auth, json=body) for _ in range(2)))
    assert [200, 200] == [response.status_code for response in responses]
    assert 1 == responses[0].json()['operation']['revision'] == responses[1].json()['operation']['revision']
    assert 409 == (await client.post(url+'/lifecycle/restore', headers=auth, json=body)).status_code
    assert 410 == (await client.post(BASE, headers=auth, **multipart(data))).status_code
    reuse = metadata(duplicate_mode='reuse', duplicate_report_id=report['id'])
    assert 410 == (await client.post(BASE, headers=auth, **multipart(reuse))).status_code
    _, restore_body = await act(client, url, auth, 'restore')
    assert 409 == (await client.post(url+'/lifecycle/purge', headers=auth, json=request(await management(client, url, auth), 'purge'))).status_code
    await act(client, url, auth, 'trash')
    assert 'trash' == (await client.post(url+'/lifecycle/restore', headers=auth, json=restore_body)).json()['workspace']['report']['archive_status']
    purge = request(await management(client, url, auth), 'purge')
    responses = await asyncio.gather(*(client.post(url+'/lifecycle/purge', headers=auth, json=purge) for _ in range(2)))
    assert [200, 200] == [response.status_code for response in responses]
    assert all(response.json()['deleted'] and response.json()['workspace'] is None for response in responses)
    assert 410 == (await client.post(BASE, headers=auth, **multipart(data))).status_code
    assert (await client.post(url+'/lifecycle/trash', headers=auth, json=body)).json()['deleted'] is True
    assert 404 == (await client.post(url+'/lifecycle/restore', headers=auth, json=request(state, 'restore'))).status_code
    assert 0 == (await client.get(BASE, headers=auth)).json()['total']


@pytest.mark.asyncio
async def test_state_changes_require_new_confirmation_and_strict_delete(client, db_session, processing):
    _, report, url, auth = await setup(client, db_session)
    state = await management(client, url, auth)
    fields = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
    assert 200 == (await client.patch(url, headers=auth, json=fields | {'title': '其他窗口新名称', 'expected_revision': 0})).status_code
    assert 409 == (await client.post(url+'/lifecycle/trash', headers=auth, json=request(state, 'trash'))).status_code
    assert 'archived' == (await management(client, url, auth))['report']['archive_status']
    await act(client, url, auth, 'trash')
    for flag in [False, 1, None, 'true']:
        assert 422 == (await client.post(url+'/lifecycle/purge', headers=auth, json=request(await management(client, url, auth), 'purge', confirmed_permanent_delete=flag))).status_code
    assert 422 == (await client.get(BASE, headers=auth, params={'archive': 'invalid'})).status_code
    assert 'trash' == (await management(client, url, auth))['report']['archive_status']


@pytest.mark.asyncio
@pytest.mark.parametrize('after', ['restore', 'purge'])
async def test_already_dispatched_late_response_cannot_publish_after_lifecycle(client, db_session, test_engine, processing, monkeypatch, after):
    _, report, url, auth = await setup(client, db_session)
    p = await preview(client, url, auth, [{'page': 1, 'text': LINE}])
    result = await client.post(url+'/ai', headers=auth, json=consent(p)); assert 202 == result.status_code
    job_id = result.json()['job']['id']; started, release = asyncio.Event(), asyncio.Event()
    async def transport(request):
        processing['wire'].append(json.loads(request.content)); started.set(); await release.wait()
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'synthetic-model', 'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': CONTENT}}]})
    monkeypatch.setattr(processing_service, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    task = asyncio.create_task(processing_service.run_job(job_id))
    try:
        await asyncio.wait_for(started.wait(), 10)
        assert (await management(client, url, auth))['has_dispatched_text'] is True
        await act(client, url, auth, 'trash'); await act(client, url, auth, after)
        release.set(); await asyncio.wait_for(task, 10)
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert 1 == len(processing['wire'])
    await processing_service.run_job(job_id)
    assert 1 == len(processing['wire'])
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        job = await processing_service.load_job(db, job_id, payload=True)
        if after == 'purge': assert job is None and await db.get(PatientReport, UUID(report['id'])) is None
        else:
            assert job.status == 'cancelled' and job.result == {} and job.lease is None
            view = await workflow_view(client, url, auth)
            assert view['ai_job'] is None and view['preview'] is None


@pytest.mark.asyncio
async def test_late_ocr_and_scanner_do_not_resume_recycled_report(client, db_session, test_engine, processing, monkeypatch):
    _, report, url, auth = await setup(client, db_session)
    body = workflow_version(await workflow_view(client, url, auth)) | {'request_id': str(uuid4())}
    response = await client.post(url+'/extract', headers=auth, json=body); assert 202 == response.status_code
    identifier = response.json()['job']['id']; started, release = asyncio.Event(), asyncio.Event()
    async def slow(*_):
        started.set(); await release.wait(); return {'pages': [{'page': 1, 'text': LINE, 'method': 'local_ocr'}]}
    monkeypatch.setattr(processing_service, 'extract_report_file', slow)
    task = asyncio.create_task(processing_service.run_job(identifier))
    try:
        await asyncio.wait_for(started.wait(), 10)
        await act(client, url, auth, 'trash')
        # 模拟旧队列残留/错误状态，scanner仍不能投回收站报告。
        async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
            job = await processing_service.load_job(db, identifier); job.status = 'queued'; await db.commit()
        assert identifier not in await processing_service.pending_jobs()
        await act(client, url, auth, 'restore')
        release.set(); await asyncio.wait_for(task, 10)
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    view = await workflow_view(client, url, auth)
    assert view['extract_job'] is None and view['preview'] is None
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        job = await processing_service.load_job(db, identifier, payload=True)
        assert 'cancelled' == job.status and {} == job.result
