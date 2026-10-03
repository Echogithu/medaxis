"""真实 PostgreSQL：授权快照、身份隔离、幂等并发和双端回复。"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api import deps
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.consultation import Consultation, ConsultationMessage
from app.models.document_parse import DocumentParseTask
from app.models.medical_case import MedicalCase
from app.models.notification import Notification
from app.models.user import User, UserRole, UserStatus


@pytest.fixture(autouse=True)
def local_auth_cache(monkeypatch):
    async def get(_): return None
    monkeypatch.setattr(deps, 'get_redis', lambda: SimpleNamespace(get=get))


def headers(user):
    return {'Authorization': f'Bearer {create_access_token(str(user.id), platform="web")}'}


async def seed(db):
    users = [User(id=uuid4(), email=f'{uuid4()}@example.invalid', full_name=name, role=role,
        status=UserStatus.ACTIVE, is_verified=verified, hashed_password='unused', hospital='合成机构', department='合成科室')
        for name, role, verified in [('合成患者', UserRole.PATIENT, False), ('其他患者', UserRole.PATIENT, False),
            ('复核医生', UserRole.DOCTOR, True), ('其他医生', UserRole.DOCTOR, True), ('未认证医生', UserRole.DOCTOR, False)]]
    db.add_all(users)
    await db.flush()
    case = MedicalCase(id=uuid4(), patient_id=users[0].id, title='合成病例', description='原始患者事实', ai_diagnosis_summary='AI 原始总结')
    db.add(case)
    await db.commit()
    return (*users, case)


async def payload(client, patient, doctor, case, **extra):
    response = await client.get(f'/api/v1/consultations/preview/{case.id}', headers=headers(patient))
    assert 200 == response.status_code, response.text
    return dict(request_id=str(uuid4()), case_id=str(case.id), doctor_id=str(doctor.id), question='请核对本次资料',
        source_fingerprint=response.json()['source_fingerprint'], material_ids=[], share_confirmed=True, **extra)


async def post(client, user, path, data):
    return await client.post('/api/v1/consultations'+path, headers=headers(user), json=data)


async def detail(client, user, item):
    response = await client.get('/api/v1/consultations/'+item['id'], headers=headers(user))
    assert 200 == response.status_code, response.text
    return response.json()


def action(item, name, **extra):
    return dict(request_id=str(uuid4()), expected_revision=item['revision'], action=name, **extra)


@pytest.mark.asyncio
async def test_snapshot_reply_followup_cancel_and_identity_isolation(client, db_session):
    p, other, d, stranger, unverified, case = await seed(db_session)
    task = DocumentParseTask(file_id=uuid4().hex, filename='合成检查.png', parse_method='image', status='completed',
        file_bytes=b'synthetic', owner_user_id=p.id, case_id=case.id,
        result={'indicators': [], 'overall_confidence': 1, 'requires_manual_review': False})
    db_session.add(task)
    await db_session.commit()
    data = await payload(client, p, d, case)
    data['material_ids'] = [task.file_id]
    first = await post(client, p, '', data)
    assert 201 == first.status_code, first.text
    item = first.json()
    assert item == (await post(client, p, '', data)).json()
    changed = {**data, 'question': '变更内容'}
    assert 409 == (await post(client, p, '', changed)).status_code
    for user in [other, stranger]:
        assert 404 == (await client.get('/api/v1/consultations/'+item['id'], headers=headers(user))).status_code
    assert 403 == (await client.get('/api/v1/consultations/'+item['id'], headers=headers(unverified))).status_code
    snapshot = (await detail(client, d, item))['snapshot']
    assert '原始患者事实' == snapshot['description'] and 'AI 原始总结' == snapshot['ai_summary']
    assert [task.file_id] == [m['file_id'] for m in snapshot['materials']]
    assert 'file_bytes' not in snapshot['materials'][0] and 'file_path' not in snapshot['materials'][0]
    case.description = '后来补充的患者事实'
    await db_session.commit()
    assert snapshot == (await detail(client, d, item))['snapshot']
    accepted = await post(client, d, '/'+item['id']+'/actions', action(item, 'accept'))
    assert 200 == accepted.status_code, accepted.text
    item = accepted.json()
    reply = dict(request_id=str(uuid4()), expected_revision=item['revision'], body='合成专业建议', category='visit_advice', next_state='awaiting_patient')
    response = await post(client, d, '/'+item['id']+'/messages', reply)
    assert 200 == response.status_code, response.text
    item = response.json()
    assert item == (await post(client, d, '/'+item['id']+'/messages', reply)).json()
    view = await detail(client, p, item)
    assert '合成专业建议' == view['messages'][-1]['body']
    assert '复核医生' == view['messages'][-1]['author']['name']
    followup = dict(request_id=str(uuid4()), expected_revision=item['revision'], body='合成追问')
    item = (await post(client, p, '/'+item['id']+'/messages', followup)).json()
    assert 'accepted' == item['state']
    assert '合成追问' == (await detail(client, d, item))['messages'][-1]['body']
    row = await db_session.get(MedicalCase, case.id, populate_existing=True)
    assert 'AI 原始总结' == row.ai_diagnosis_summary and row.doctor_diagnosis is None and row.assigned_doctor_id is None
    notification = (await client.get('/api/v1/consultations/notifications', headers=headers(p))).json()[0]
    assert '合成专业建议' not in notification['subject']
    assert 404 == (await post(client, other, f'/notifications/{notification["id"]}/read', {})).status_code
    assert 200 == (await post(client, p, f'/notifications/{notification["id"]}/read', {})).status_code
    assert item['state'] == (await detail(client, p, item))['state']
    cancelled = await post(client, p, '/'+item['id']+'/actions', action(item, 'cancel'))
    assert 200 == cancelled.status_code
    item = cancelled.json()
    assert 'cancelled' == (await detail(client, p, item))['state']
    assert 403 == (await client.get('/api/v1/consultations/'+item['id'], headers=headers(d))).status_code
    assert 409 == (await post(client, d, '/'+item['id']+'/messages', {**reply, 'request_id': str(uuid4()), 'expected_revision': item['revision']})).status_code
    replacement = await payload(client, p, stranger, case)
    assert 201 == (await post(client, p, '', replacement)).status_code


@pytest.mark.asyncio
async def test_invalid_scope_consent_and_unavailable_doctor(client, db_session):
    p, other, d, stranger, unverified, case = await seed(db_session)
    data = await payload(client, p, d, case)
    assert 404 == (await client.get(f'/api/v1/consultations/preview/{case.id}', headers=headers(other))).status_code
    assert 422 == (await post(client, p, '', {**data, 'share_confirmed': False})).status_code
    assert 422 == (await post(client, p, '', {**data, 'question': '  '})).status_code
    assert 409 == (await post(client, p, '', {**data, 'doctor_id': str(unverified.id)})).status_code
    assert 404 == (await post(client, p, '', {**data, 'material_ids': ['other-case-file']})).status_code
    case.description = '资料已变更'
    await db_session.commit()
    assert 409 == (await post(client, p, '', data)).status_code
    data = await payload(client, p, d, case)
    item = (await post(client, p, '', data)).json()
    d.is_verified = False
    await db_session.commit()
    assert 403 == (await client.get('/api/v1/consultations/'+item['id'], headers=headers(d))).status_code
    first = await detail(client, p, item)
    assert 'unavailable' == first['state']
    assert first == await detail(client, p, item)
    d.is_verified = True
    await db_session.commit()
    assert 403 == (await client.get('/api/v1/consultations/'+item['id'], headers=headers(d))).status_code
    assert 'unavailable' == (await detail(client, p, item))['state']
    assert 201 == (await post(client, p, '', await payload(client, p, stranger, case))).status_code


@pytest.mark.asyncio
async def test_decline_and_explicit_completion(client, db_session):
    p, _, d, stranger, _, case = await seed(db_session)
    item = (await post(client, p, '', await payload(client, p, d, case))).json()
    assert 422 == (await post(client, d, '/'+item['id']+'/actions', action(item, 'decline'))).status_code
    response = await post(client, d, '/'+item['id']+'/actions', action(item, 'decline', reason='合成范围不适合'))
    assert 200 == response.status_code
    assert '合成范围不适合' == (await detail(client, p, item))['messages'][-1]['body']
    item = (await post(client, p, '', await payload(client, p, stranger, case))).json()
    item = (await post(client, stranger, '/'+item['id']+'/actions', action(item, 'accept'))).json()
    reply = dict(request_id=str(uuid4()), expected_revision=item['revision'], body='合成资料解读', category='report_explanation', next_state='completed')
    response = await post(client, stranger, '/'+item['id']+'/messages', reply)
    assert 200 == response.status_code
    assert 'completed' == response.json()['state']
    assert '合成资料解读' == (await detail(client, p, item))['messages'][-1]['body']


@pytest.mark.asyncio
async def test_concurrent_submission_accept_and_cancel_publish(client, db_session, test_engine):
    p, _, d, _, _, case = await seed(db_session)
    data = await payload(client, p, d, case)
    await db_session.commit()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as concurrent:
            replies = await asyncio.gather(post(concurrent, p, '', data), post(concurrent, p, '', {**data, 'request_id': str(uuid4())}))
            assert [201, 409] == sorted(r.status_code for r in replies), [r.text for r in replies]
            item = next(r.json() for r in replies if r.status_code == 201)
            accept = action(item, 'accept')
            replies = await asyncio.gather(*[post(concurrent, d, '/'+item['id']+'/actions', accept) for _ in range(2)])
            assert [200, 200] == [r.status_code for r in replies], [r.text for r in replies]
            item = replies[0].json()
            reply = dict(request_id=str(uuid4()), expected_revision=item['revision'], body='并发合成回复', category='health_advice', next_state='awaiting_patient')
            replies = await asyncio.gather(post(concurrent, d, '/'+item['id']+'/messages', reply),
                post(concurrent, p, '/'+item['id']+'/actions', action(item, 'cancel')))
            assert [200, 409] == sorted(r.status_code for r in replies), [r.text for r in replies]
            current = await detail(concurrent, p, item)
            if current['state'] != 'cancelled':
                assert 200 == (await post(concurrent, p, '/'+item['id']+'/actions', action(current, 'cancel'))).status_code
            assert 403 == (await concurrent.get('/api/v1/consultations/'+item['id'], headers=headers(d))).status_code
        async with factory() as fresh:
            assert 1 == await fresh.scalar(select(func.count()).select_from(Consultation).where(Consultation.case_id == case.id))
            assert 1 == await fresh.scalar(select(func.count()).select_from(ConsultationMessage).where(ConsultationMessage.consultation_id == item['id'], ConsultationMessage.kind == 'accept'))
    finally:
        app.dependency_overrides.clear()
