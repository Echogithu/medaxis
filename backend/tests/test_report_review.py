"""真实数据库核对版本：人工草稿/精确确认/幂等/历史与来源失效。"""
import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_db
from app.main import app
from app.models.agent import CarePlan, PatientHealthProfile
from app.models.patient_report import PatientReport, ReportProcessingJob, ReportReviewVersion
from app.models.user import UserRole
from app.services import report_review as service
from app.services.report_candidates import fingerprint
from tests.test_patient_care_plans import headers, patient
from tests.test_patient_reports import BASE, create


@pytest.fixture
async def client(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def fresh():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = fresh
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as api:
            yield api
    finally: app.dependency_overrides.clear()


def content(value='阳性'):
    return {'indicators': [{'name': '合成定性项目', 'raw_value': value, 'unit': None, 'reference_range': None,
        'abnormal_mark': None, 'source_page': None, 'evidence': None}], 'sections': []}


def version(view):
    return {'expected_revision': view['revision'], 'expected_source_epoch': view['source_epoch'],
        'expected_source_version': view['source_version'], 'expected_source_hash': view['source_hash']}


async def setup(client, db, **changes):
    user = await patient(db)
    report = await create(client, user, data=None)
    url, auth = BASE+'/'+report['id'], headers(user)
    if changes:
        fields = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
        response = await client.patch(url, headers=auth, json=fields | {'expected_revision': report['revision']} | changes)
        assert response.status_code == 200
        report = response.json()
    return user, report, url, auth


async def view(client, url, auth):
    response = await client.get(url+'/review', headers=auth)
    assert response.status_code == 200
    return response.json()


async def save(client, url, auth, value=None, **changes):
    body = version(await view(client, url, auth)) | {'request_id': str(uuid4()), 'content': value or content()} | changes
    response = await client.post(url+'/review/drafts', headers=auth, json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


async def confirm(client, url, auth):
    state = await view(client, url, auth)
    body = version(state) | {'request_id': str(uuid4()), 'draft_id': state['draft']['id'], 'checked_against_original': True}
    response = await client.post(url+'/review/confirm', headers=auth, json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


@pytest.mark.asyncio
async def test_manual_draft_exact_confirm_history_replay_and_no_health_writes(client, db_session, test_engine):
    user, report, url, auth = await setup(client, db_session)
    original = await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)
    saved, body = await save(client, url, auth)
    assert saved['workspace']['confirmed'] is None and saved['workspace']['review_status'] == 'draft'
    for key in ['unit', 'reference_range', 'abnormal_mark', 'source_page', 'evidence']:
        assert saved['version']['content']['indicators'][0][key] is None
    replay = await client.post(url+'/review/drafts', headers=auth, json=body)
    assert replay.json()['version']['id'] == saved['version']['id']
    assert 409 == (await client.post(url+'/review/drafts', headers=auth, json=body | {'content': content('阴性')})).status_code
    state = saved['workspace']
    confirm_body = version(state) | {'request_id': str(uuid4()), 'draft_id': saved['version']['id']}
    for checked in [False, 1, 'true', None]:
        response = await client.post(url+'/review/confirm', headers=auth, json=confirm_body | {'checked_against_original': checked})
        assert response.status_code == 422
    confirmed, confirm_body = await confirm(client, url, auth)
    assert confirmed['version']['content'] == saved['version']['content']
    assert confirmed['version']['confirmed_draft_id'] == saved['version']['id']
    assert confirmed['workspace']['review_status'] == 'patient_confirmed'
    assert (await client.post(url+'/review/confirm', headers=auth, json=confirm_body)).json()['version']['id'] == confirmed['version']['id']
    next_draft, _ = await save(client, url, auth, content('弱阳性'), based_on_version_id=saved['version']['id'])
    assert next_draft['workspace']['confirmed']['content'] == confirmed['version']['content']
    assert next_draft['workspace']['review_status'] == 'draft'
    historical = (await client.get(url+'/review/versions/'+confirmed['version']['id'], headers=auth)).json()
    assert historical['content']['indicators'][0]['raw_value'] == '阳性'
    history = (await client.get(url+'/review/history?limit=2&page=1', headers=auth)).json()
    assert history['total'] == 3 and [3, 2] == [item['revision'] for item in history['items']]
    assert all('content' not in item for item in history['items'])
    assert [1] == [item['revision'] for item in (await client.get(url+'/review/history?limit=2&page=2', headers=auth)).json()['items']]
    assert original.content == (await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)).content
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        version_row = await db.get(ReportReviewVersion, UUID(confirmed['version']['id']))
        assert 'payload' not in version_row.__dict__
        assert [] == (await db.scalars(select(CarePlan).where(CarePlan.patient_id == user.id))).all()
        assert [] == (await db.scalars(select(PatientHealthProfile).where(PatientHealthProfile.patient_id == user.id))).all()


@pytest.mark.asyncio
async def test_conflict_concurrent_save_and_confirm_never_take_unsaved_body(client, db_session):
    _, _, url, auth = await setup(client, db_session)
    state = await view(client, url, auth)
    first = version(state) | {'request_id': str(uuid4()), 'content': content('首次')}
    replies = await asyncio.gather(*(client.post(url+'/review/drafts', headers=auth, json=first) for _ in range(2)))
    assert [201, 201] == [item.status_code for item in replies]
    assert replies[0].json()['version']['id'] == replies[1].json()['version']['id']
    stale = await client.post(url+'/review/drafts', headers=auth, json=first | {'request_id': str(uuid4()), 'content': content('未保存')})
    assert stale.status_code == 409
    state = await view(client, url, auth)
    body = version(state) | {'request_id': str(uuid4()), 'draft_id': state['draft']['id'], 'checked_against_original': True}
    assert 422 == (await client.post(url+'/review/confirm', headers=auth, json=body | {'content': content('偷换')})).status_code
    _, _ = await save(client, url, auth, content('新的草稿'))
    assert 409 == (await client.post(url+'/review/confirm', headers=auth, json=body)).status_code
    assert (await view(client, url, auth))['confirmed'] is None


@pytest.mark.asyncio
async def test_source_epoch_preview_changes_category_toggle_and_metadata_do_not_revive(client, db_session):
    _, report, url, auth = await setup(client, db_session)
    await save(client, url, auth); confirmed, _ = await confirm(client, url, auth)
    fields = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
    updated = await client.patch(url, headers=auth, json=fields | {'title': '只改标题', 'expected_revision': 0})
    assert updated.status_code == 200 and updated.json()['review_status'] == 'patient_confirmed'
    workflow = (await client.get(url+'/workspace', headers=auth)).json()
    body = {'expected_source_version': workflow['source_version'], 'expected_workflow_revision': workflow['revision'], 'pages': [{'page': 1, 'text': '新的关键文字'}]}
    assert 200 == (await client.post(url+'/preview', headers=auth, json=body)).status_code
    state = await view(client, url, auth)
    assert state['review_status'] == 'source_changed' and not state['confirmed']['source_current']
    epoch = state['source_epoch']
    workflow = (await client.get(url+'/workspace', headers=auth)).json()
    body['expected_workflow_revision'] = workflow['revision']
    assert 200 == (await client.post(url+'/preview', headers=auth, json=body)).status_code
    assert epoch == (await view(client, url, auth))['source_epoch']
    for revision, category in [(1, 'imaging'), (2, 'lab')]:
        assert 200 == (await client.patch(url, headers=auth, json=fields | {'expected_revision': revision, 'category': category})).status_code
    state = await view(client, url, auth)
    assert state['source_epoch'] == epoch + 2 and state['review_status'] == 'source_changed'
    assert state['confirmed']['id'] == confirmed['version']['id']
    saved, _ = await save(client, url, auth, content('按新原件填写'), based_on_version_id=state['draft']['id'])
    assert saved['workspace']['confirmed']['id'] == confirmed['version']['id']
    latest, _ = await confirm(client, url, auth)
    assert latest['workspace']['review_status'] == 'patient_confirmed'


@pytest.mark.asyncio
async def test_ai_candidate_is_explicit_reference_original_stays_immutable(client, db_session, test_engine):
    _, report, url, auth = await setup(client, db_session)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    original = content('机器原值')
    original['indicators'][0].update(source_page=1, evidence='合成定性项目 机器原值')
    async with factory() as db:
        row = await db.get(PatientReport, UUID(report['id']))
        preview = {'hash': 'synthetic-candidate-hash'}
        job = ReportProcessingJob(report_id=row.id, request_id=uuid4(), request_fingerprint='0'*64, kind='ai', status='completed',
            source_version=row.source_version, source_hash=fingerprint([row.source_version, row.content_hash, row.category]),
            input={}, result=deepcopy(original) | {'preview_hash': preview['hash']})
        db.add(job); await db.flush()
        row.workflow = {'revision': 1, 'preview': preview, 'ai_id': str(job.id)}
        await db.commit(); candidate_id = str(job.id)
    state = await view(client, url, auth)
    assert state['candidate']['content'] == original and state['draft'] is None
    saved, _ = await save(client, url, auth, content('患者修正值'), candidate_job_id=candidate_id)
    assert saved['version']['candidate_job_id'] == candidate_id
    historical = (await client.get(url+'/review/versions/'+saved['version']['id'], headers=auth)).json()
    assert historical['original_candidate']['indicators'][0]['raw_value'] == '机器原值'
    assert historical['content']['indicators'][0]['raw_value'] == '患者修正值'


@pytest.mark.asyncio
async def test_draft_incomplete_unknown_and_imaging_text_confirmation(client, db_session):
    _, _, url, auth = await setup(client, db_session)
    incomplete = content('')
    incomplete['indicators'][0]['unit'] = '  '
    saved, _ = await save(client, url, auth, incomplete)
    assert saved['version']['content']['indicators'][0]['unit'] is None
    state = await view(client, url, auth)
    body = version(state) | {'request_id': str(uuid4()), 'draft_id': state['draft']['id'], 'checked_against_original': True}
    assert 422 == (await client.post(url+'/review/confirm', headers=auth, json=body)).status_code
    invalid = content(); invalid['indicators'][0]['source_page'] = 2
    assert 422 == (await client.post(url+'/review/drafts', headers=auth, json=version(state) | {'request_id': str(uuid4()), 'content': invalid})).status_code
    _, _, url, auth = await setup(client, db_session, category='imaging')
    text = {'indicators': [], 'sections': [{'kind': 'findings', 'text': '合成书面所见', 'source_page': None, 'evidence': None}]}
    await save(client, url, auth, text)
    confirmed, _ = await confirm(client, url, auth)
    assert confirmed['workspace']['review_status'] == 'patient_confirmed'
    assert confirmed['version']['content']['indicators'] == []


@pytest.mark.asyncio
async def test_pending_stats_history_isolation_and_roles(client, db_session):
    owner, _, url, auth = await setup(client, db_session)
    _, _, own_url, second_auth = await setup(client, db_session)
    other = await patient(db_session)
    await save(client, url, auth); confirmed, _ = await confirm(client, url, auth)
    listing = (await client.get(BASE, headers=auth)).json()
    assert listing['stats']['archived'] == 1 and listing['stats']['pending_review'] == 0
    assert (await client.get(BASE+'?pending_only=true', headers=auth)).json()['items'] == []
    for suffix in ['/review', '/review/history', '/review/versions/'+confirmed['version']['id']]:
        assert 404 == (await client.get(url+suffix, headers=headers(other))).status_code
    assert 404 == (await client.get(own_url+'/review/versions/'+confirmed['version']['id'], headers=second_auth)).status_code
    second_view = await view(client, own_url, second_auth)
    assert 404 == (await client.post(own_url+'/review/drafts', headers=second_auth, json=version(second_view) | {
        'request_id': str(uuid4()), 'content': content(), 'based_on_version_id': confirmed['version']['id']})).status_code
    state = await view(client, url, auth)
    body = version(state) | {'request_id': str(uuid4()), 'content': content(), 'based_on_version_id': str(uuid4())}
    assert 404 == (await client.post(url+'/review/drafts', headers=auth, json=body)).status_code
    for action in ['drafts', 'confirm']:
        assert 404 == (await client.post(url+'/review/'+action, headers=headers(other), json={})).status_code
    doctor = await patient(db_session); doctor.role = UserRole.DOCTOR; await db_session.commit()
    assert 403 == (await client.get(url+'/review', headers=headers(doctor))).status_code
    assert 401 == (await client.get(url+'/review')).status_code
    await save(client, url, auth, content('未确认更新'))
    listing = (await client.get(BASE+'?pending_only=true', headers=headers(owner))).json()
    assert listing['total'] == 1 and listing['stats']['pending_review'] == 1
