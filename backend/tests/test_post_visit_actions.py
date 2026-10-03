"""合成资料及模型，真实 PostgreSQL 验证诊后AI隐私、确认、失效与提醒。"""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.agent import CarePlan, MonitoringEvent
from app.models.medical_case import MedicalCase
from app.models.post_visit_feedback import PatientPostVisitFeedback
from app.schemas.post_visit_actions import GenerateActions, MedicationConfirmation
from app.services import post_visit_actions as service
from app.services.care_plan import today
from app.tasks import monitoring
from tests.test_patient_care_plans import patient, headers

RECIPIENT = {'provider': 'synthetic', 'model': 'synthetic-model', 'host': 'example.invalid', 'route_hash': 'synthetic-route'}
CONFIG = {'api_key': 'synthetic-unused', 'base_url': 'https://example.invalid/v1', 'default_model': 'synthetic-model'}
FOLLOW = '三天后复查合成项目'
DRUG = '示例药每次1片每日08:00服用'


@pytest.fixture
def fake_model(monkeypatch):
    calls = []
    async def recipient(_db): return deepcopy(RECIPIENT), deepcopy(CONFIG)
    async def chat(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=json.dumps({'follow_ups': [{'description': FOLLOW, 'evidence': FOLLOW}],
            'medications': [{'name': '示例药', 'dosage': '1片', 'evidence': DRUG, 'times': ['08:00']}]}))
    monkeypatch.setattr(service, 'model_recipient', recipient)
    monkeypatch.setattr(service.ConsentedLLM, 'chat', chat)
    monkeypatch.setattr(service, 'enqueue_events', lambda _events: None)
    return calls


async def source(client, db):
    user = await patient(db)
    user.full_name, user.phone = '合成患者姓名', '13800000000'
    case = MedicalCase(patient_id=user.id, title='合成诊后来源')
    db.add(case); await db.commit()
    auth = headers(user)
    url = f'/api/v1/patient/cases/{case.id}'
    body = {'patient_summary': f'{user.full_name} 电话{user.phone} 邮箱{user.email}。{DRUG}',
            'actual_department': '不得外发科室', 'follow_up_items': [FOLLOW]}
    response = await client.post(url+'/post-visit-feedback', headers=auth, json=body)
    assert 200 == response.status_code, response.text
    return user, url, auth, body, response.json()['feedback']


async def generate(client, url, auth):
    preview = await client.get(url+'/ai-actions/preview', headers=auth)
    assert 200 == preview.status_code, preview.text
    view = preview.json()
    response = await client.post(url+'/ai-actions/generate', headers=auth,
        json={k: view[k] for k in ['source_revision', 'preview_hash']} | {'consent': True})
    assert 200 == response.status_code, response.text
    return view, response.json()['draft']


def confirmation(draft, **changes):
    date = (today()+timedelta(days=1)).isoformat()
    body = {'draft_id': draft['id'], 'source_revision': draft['source_revision'], 'channel': 'in_app',
            'follow_ups': [{'id': draft['follow_ups'][0]['id'], 'due_date': date}],
            'medications': [{'id': draft['medications'][0]['id'], 'start_date': date, 'end_date': date, 'times': ['08:00', '20:00']}]}
    return body | changes


@pytest.mark.asyncio
async def test_preview_consent_and_no_effect_before_confirmation(client, db_session, fake_model):
    user, url, auth, _, _ = await source(client, db_session)
    view = (await client.get(url+'/ai-actions/preview', headers=auth)).json()
    assert not fake_model
    for hidden in [user.full_name, user.phone, user.email, '不得外发科室', 'material_file_ids', 'revision_history']:
        assert hidden not in view['text']
    body = {'source_revision': 1, 'preview_hash': view['preview_hash'], 'consent': False}
    assert 422 == (await client.post(url+'/ai-actions/generate', headers=auth, json=body)).status_code
    body['consent'] = True; body['preview_hash'] = 'x'*64
    assert 409 == (await client.post(url+'/ai-actions/generate', headers=auth, json=body)).status_code
    await db_session.commit()
    view, draft = await generate(client, url, auth)
    assert 'ready' == draft['state'] and 1 == len(fake_model)
    assert view['text'] == fake_model[0]['messages'][0]['content']
    assert [] == (await db_session.scalars(select(CarePlan).where(CarePlan.patient_id == user.id))).all()
    assert [] == (await db_session.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all()
    assert 1 == len((await client.get('/api/v1/patient/ai-actions/pending', headers=auth)).json()['items'])
    await generate(client, url, auth)
    assert 1 == len(fake_model)


@pytest.mark.asyncio
async def test_confirm_persist_idempotence_and_source_edit_invalidates(client, db_session, test_engine, fake_model):
    user, url, auth, original, feedback = await source(client, db_session)
    _, draft = await generate(client, url, auth)
    body = confirmation(draft)
    first = await client.post(url+'/ai-actions/confirm', headers=auth, json=body)
    assert 200 == first.status_code, first.text
    confirmed = first.json()['draft']
    assert 'confirmed' == confirmed['state'] and 3 == confirmed['reminder_count']
    assert first.json() == (await client.post(url+'/ai-actions/confirm', headers=auth, json=body)).json()
    modified = deepcopy(body); modified['channel'] = 'email'
    assert 409 == (await client.post(url+'/ai-actions/confirm', headers=auth, json=modified)).status_code
    await db_session.commit()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as fresh:
        plan = await fresh.get(CarePlan, confirmed['plan_id'])
        assert 'active' == plan.status and 'ai_extracted_patient_confirmed' == plan.tasks['metadata']['source_type']
        events = (await fresh.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all()
        assert 3 == len(events) and all(e.channel == 'in_app' for e in events)
        assert {0, 12} == {e.scheduled_at.hour for e in events if e.event_type == 'medication_reminder'}
    updated = await client.patch(url+f'/post-visit-feedback/{feedback["feedback_id"]}', headers=auth,
                                json=original | {'expected_revision': 1, 'patient_summary': '修改后的合成记录'})
    assert 200 == updated.status_code, updated.text
    assert None is (await client.get(url+'/ai-actions', headers=auth)).json()['draft']
    async with factory() as fresh:
        assert 'cancelled' == (await fresh.get(CarePlan, confirmed['plan_id'])).status
        assert all(e.status == 'cancelled' for e in (await fresh.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all())
    assert 409 == (await client.post(url+'/ai-actions/confirm', headers=auth, json=body)).status_code


@pytest.mark.asyncio
async def test_owner_isolation_dismiss_and_retry_failure(client, db_session, fake_model, monkeypatch):
    _, url, auth, _, _ = await source(client, db_session)
    other = await patient(db_session); other_auth = headers(other)
    assert 404 == (await client.get(url+'/ai-actions/preview', headers=other_auth)).status_code
    await db_session.commit()
    _, draft = await generate(client, url, auth)
    assert [] == (await client.get('/api/v1/patient/ai-actions/pending', headers=other_auth)).json()['items']
    dismissed = await client.post(url+'/ai-actions/dismiss', headers=auth, json={'draft_id': draft['id']})
    assert 'dismissed' == dismissed.json()['draft']['state']
    async def fail(*_args, **_kwargs): raise RuntimeError('不得泄露合成姓名与原始异常')
    monkeypatch.setattr(service.ConsentedLLM, 'chat', fail)
    view = (await client.get(url+'/ai-actions/preview', headers=auth)).json()
    failed = await client.post(url+'/ai-actions/generate', headers=auth, json={'source_revision':1,'preview_hash':view['preview_hash'],'consent':True})
    assert 502 == failed.status_code and '不得泄露' not in failed.text
    assert 'failed' == (await client.get(url+'/ai-actions', headers=auth)).json()['draft']['state']


@pytest.mark.asyncio
async def test_validation_preserves_candidates_without_events(client, db_session, fake_model):
    user, url, auth, _, _ = await source(client, db_session)
    _, draft = await generate(client, url, auth)
    for body in [confirmation(draft, follow_ups=[], medications=[]), confirmation(draft, follow_ups=[{'id':'foreign','due_date':today().isoformat()}]),
                 confirmation(draft, channel='sms'), confirmation(draft, medications=[{'id':draft['medications'][0]['id'],'start_date':today().isoformat(),'end_date':today().isoformat(),'times':['25:00']}])]:
        assert 422 == (await client.post(url+'/ai-actions/confirm', headers=auth, json=body)).status_code
        await db_session.commit()
    assert 'ready' == (await client.get(url+'/ai-actions', headers=auth)).json()['draft']['state']
    assert [] == (await db_session.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all()


def test_grounding_negation_and_duplicates():
    data = {'follow_ups':[{'description':FOLLOW,'evidence':FOLLOW}]*2 + [{'description':'AI虚构','evidence':FOLLOW}],
            'medications':[{'name':'示例药','dosage':'1片','evidence':DRUG}]*2}
    text = json.dumps({'patient_summary':DRUG, 'follow_up_items':[FOLLOW]})
    result = service.grounded_actions(json.dumps(data), text)
    assert 1 == len(result['follow_ups']) and 1 == len(result['medications'])
    text = json.dumps({'patient_summary':'停用'+DRUG, 'follow_up_items':[FOLLOW]})
    assert [] == service.grounded_actions(json.dumps(data), text)['medications']
    text = json.dumps({'patient_summary':'无需'+FOLLOW, 'follow_up_items':[]})
    assert [] == service.grounded_actions(json.dumps(data), text)['follow_ups']
    text = json.dumps({'patient_summary':'示例药每次11片', 'follow_up_items':[]})
    data['medications']=[{'name':'示例药','dosage':'1片','evidence':'示例药每次11片'}]
    assert [] == service.grounded_actions(json.dumps(data), text)['medications']


@pytest.mark.parametrize('times', [['08:00','08:00'], ['08:00:00'], ['08:00+08:00'], ['24:00']])
def test_strict_clock_and_consent(times):
    with pytest.raises(ValueError): MedicationConfirmation(id='x',start_date=today(),end_date=today(),times=times)
    with pytest.raises(ValueError): GenerateActions(source_revision=1,preview_hash='x'*64,consent=False)
    with pytest.raises(ValueError): GenerateActions(source_revision=1,preview_hash='x'*64,consent=1)


@pytest.mark.asyncio
async def test_worker_inapp_source_guard_and_generic_mail(client, db_session, test_engine, fake_model, monkeypatch):
    user, url, auth, _, _ = await source(client, db_session)
    _, draft = await generate(client, url, auth)
    await client.post(url+'/ai-actions/confirm', headers=auth, json=confirmation(draft))
    events = (await db_session.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all()
    for e in events: e.scheduled_at = datetime.now(timezone.utc)-timedelta(minutes=1)
    await db_session.commit()
    calls = []
    async def smtp(**kwargs): calls.append(kwargs); return True, 'accepted'
    monkeypatch.setattr(monitoring.email_service, 'send_email', smtp)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    assert 'sent' == await monitoring._claim_and_send(str(events[0].id), factory)
    assert not calls
    async with factory() as fresh:
        e = await fresh.get(MonitoringEvent, events[1].id); e.channel='email'; e.payload={**e.payload,'email':'foreign@example.invalid'}
        await fresh.commit()
    assert 'sent' == await monitoring._claim_and_send(str(events[1].id), factory)
    assert user.email == calls[0]['to_email'] and '示例药' not in json.dumps(calls[0],default=str) and '复查合成' not in json.dumps(calls[0],default=str)
    async with factory() as fresh:
        row = (await fresh.scalars(select(PatientPostVisitFeedback).where(PatientPostVisitFeedback.case_id == user_case(url)))).one()
        row.revision += 1; await fresh.commit()
    assert 'skipped' == await monitoring._claim_and_send(str(events[2].id), factory)
    assert 1 == len(calls)


def user_case(url): return url.split('/')[-1]


@pytest.mark.asyncio
async def test_model_change_requires_new_consent(client, db_session, fake_model, monkeypatch):
    _, url, auth, _, _ = await source(client, db_session)
    view = (await client.get(url+'/ai-actions/preview', headers=auth)).json()
    async def changed(_db): return RECIPIENT | {'route_hash':'changed-route'}, CONFIG
    monkeypatch.setattr(service,'model_recipient',changed)
    response = await client.post(url+'/ai-actions/generate',headers=auth,
        json={'source_revision':1,'preview_hash':view['preview_hash'],'consent':True})
    assert 409 == response.status_code and not fake_model


@pytest.mark.asyncio
async def test_source_edit_during_generation_discards_response(client, db_session, fake_model, monkeypatch):
    user, url, auth, original, feedback = await source(client, db_session)
    async def changes_source(self, **_kwargs):
        response=await client.patch(url+f'/post-visit-feedback/{feedback["feedback_id"]}',headers=auth,
            json=original | {'expected_revision':1,'patient_summary':'来源已修改'})
        assert 200 == response.status_code
        return SimpleNamespace(content=json.dumps({'follow_ups':[{'description':FOLLOW,'evidence':FOLLOW}]}))
    monkeypatch.setattr(service.ConsentedLLM,'chat',changes_source)
    view=(await client.get(url+'/ai-actions/preview',headers=auth)).json()
    response=await client.post(url+'/ai-actions/generate',headers=auth,
        json={'source_revision':1,'preview_hash':view['preview_hash'],'consent':True})
    assert 409 == response.status_code
    await db_session.commit()
    assert None is (await client.get(url+'/ai-actions',headers=auth)).json()['draft']
    assert [] == (await db_session.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all()


@pytest.mark.asyncio
async def test_dismiss_confirmed_cancels_and_allows_new_draft(client, db_session, test_engine, fake_model):
    user,url,auth,_,_=await source(client,db_session)
    _,draft=await generate(client,url,auth)
    confirmed=(await client.post(url+'/ai-actions/confirm',headers=auth,json=confirmation(draft))).json()['draft']
    dismissed=await client.post(url+'/ai-actions/dismiss',headers=auth,json={'draft_id':draft['id']})
    assert 'dismissed' == dismissed.json()['draft']['state']
    factory=async_sessionmaker(test_engine,expire_on_commit=False)
    async with factory() as fresh:
        assert 'cancelled' == (await fresh.get(CarePlan,confirmed['plan_id'])).status
        assert all(e.status=='cancelled' for e in (await fresh.scalars(select(MonitoringEvent).where(MonitoringEvent.patient_id == user.id))).all())
    _,next_draft=await generate(client,url,auth)
    assert next_draft['id'] != draft['id'] and 'ready' == next_draft['state']
