"""真实 PostgreSQL 随访链路：来源、执行、并发、失效与本人隔离。"""
import asyncio
from types import SimpleNamespace
from datetime import timedelta, datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.agent import CarePlan, MonitoringEvent
from app.models.medical_case import MedicalCase
from app.models.user import User, UserRole, UserStatus
from app.services.care_plan import today
from app.tasks import monitoring


async def patient(db):
    user = User(email=f'followup-{uuid4()}@example.invalid', full_name='合成随访患者',
                hashed_password='unused', role=UserRole.PATIENT, status=UserStatus.ACTIVE)
    db.add(user)
    await db.commit()
    return user


def headers(user):
    return {'Authorization': f'Bearer {create_access_token(str(user.id), platform="web") }'}


def payload(**kwargs):
    date = today().isoformat()
    result = dict(request_id=str(uuid4()), title='合成复查计划', description='手动登记',
        start_date=date, end_date=(today()+timedelta(days=10)).isoformat(), tasks=[
            {'type': 'follow_up', 'description': '复查事项', 'due_date': date},
            {'type': 'self_check', 'description': '自测数值', 'due_date': date, 'unit': '合成单位'},
        ])
    result.update(kwargs)
    return result


async def create(client, user, **kwargs):
    response = await client.post('/api/v1/patient/care-plans', headers=headers(user), json=payload(**kwargs))
    assert 201 == response.status_code, response.text
    return response.json()


async def action(client, user, plan, name):
    response = await client.post(f'/api/v1/patient/care-plans/{plan["id"]}/actions', headers=headers(user),
                                json={'action': name, 'expected_revision': plan['revision']})
    assert 200 == response.status_code, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_confirm_checkin_and_new_session_persistence(client, db_session, test_engine):
    user = await patient(db_session)
    case = MedicalCase(patient_id=user.id, title='本人复查来源')
    db_session.add(case)
    await db_session.commit()
    data = payload(source_case_id=str(case.id))
    first = await client.post('/api/v1/patient/care-plans', headers=headers(user), json=data)
    assert 201 == first.status_code
    plan = first.json()
    assert 'pending_confirmation' == plan['status']
    assert 'patient_reported' == plan['source_type']
    assert str(case.id) == plan['source_case_id'] and '本人复查来源' == plan['source_case_title']
    repeated = await client.post('/api/v1/patient/care-plans', headers=headers(user), json=data)
    assert plan == repeated.json()
    data['title'] = '变更请求内容'
    assert 409 == (await client.post('/api/v1/patient/care-plans', headers=headers(user), json=data)).status_code
    await db_session.commit()
    task_id = plan['tasks'][0]['id']
    ack = f'/api/v1/patient/care-plans/{plan["id"]}/ack?task_id={task_id}'
    assert 409 == (await client.post(ack, headers=headers(user))).status_code
    await db_session.commit()
    active = await action(client, user, plan, 'confirm')
    assert active['confirmed_at'] and active['can_execute']
    confirmed_again = await client.post(f'/api/v1/patient/care-plans/{plan["id"]}/actions', headers=headers(user),
        json={'action': 'confirm', 'expected_revision': plan['revision']})
    assert active == confirmed_again.json()
    acked = await client.post(ack, headers=headers(user))
    assert 50 == acked.json()['plan']['progress_percent']
    check = {'plan_id': plan['id'], 'task_id': plan['tasks'][1]['id'], 'value': 123.4, 'notes': '自测备注'}
    checked = await client.post('/api/v1/patient/check-in', headers=headers(user), json=check)
    assert 200 == checked.status_code
    final = checked.json()['plan']
    assert 'completed' == final['status'] and 100 == final['progress_percent'] and final['completed_at']
    assert 'patient_reported' == final['tasks'][1]['completion_source']
    assert 123.4 == final['tasks'][1]['last_value'] and '自测备注' == final['tasks'][1]['completion_notes']
    check.update(value=999, notes='不应覆盖')
    repeated = await client.post('/api/v1/patient/check-in', headers=headers(user), json=check)
    assert final == repeated.json()['plan']
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as fresh:
        persisted = await fresh.get(CarePlan, data['request_id'])
        assert 'completed' == persisted.status and 100 == persisted.progress_percent
        assert '自测备注' == persisted.tasks['tasks'][1]['completion_notes']


@pytest.mark.asyncio
async def test_draft_edit_revision_invalid_tasks_and_ownership(client, db_session):
    user, other = await patient(db_session), await patient(db_session)
    plan = await create(client, user)
    edit = payload(title='修订后的计划')
    edit.pop('request_id')
    edit['expected_revision'] = plan['revision']
    url = f'/api/v1/patient/care-plans/{plan["id"]}'
    saved = await client.patch(url, headers=headers(user), json=edit)
    assert 200 == saved.status_code
    assert '修订后的计划' == saved.json()['title']
    assert 409 == (await client.patch(url, headers=headers(user), json=edit)).status_code
    await db_session.commit()
    assert 404 == (await client.get(url, headers=headers(other))).status_code
    assert 404 == (await client.post(url+'/ack?task_id=unknown', headers=headers(user))).status_code
    await db_session.commit()
    assert 404 == (await client.post(url+'/actions', headers=headers(other), json={'action': 'confirm', 'expected_revision': 2})).status_code
    await db_session.commit()
    foreign = MedicalCase(patient_id=other.id, title='他人病历')
    db_session.add(foreign)
    await db_session.commit()
    assert 404 == (await client.post('/api/v1/patient/care-plans', headers=headers(user), json=payload(source_case_id=str(foreign.id)))).status_code
    await db_session.commit()
    for bad in [payload(title=' '), payload(tasks=[]), payload(end_date='2000-01-01'),
                payload(tasks=[{'description': '不允许药物任务', 'type': 'medication', 'due_date': today().isoformat()}]),
                payload(source_type='doctor_verified')]:
        assert 422 == (await client.post('/api/v1/patient/care-plans', headers=headers(user), json=bad)).status_code
    assert 401 == (await client.get('/api/v1/patient/care-plans')).status_code
    assert 422 == (await client.get('/api/v1/patient/care-plans/invalid', headers=headers(user))).status_code


@pytest.mark.asyncio
async def test_pause_resume_cancel_reminders_and_worker_guard(client, db_session, test_engine, monkeypatch):
    user = await patient(db_session)
    plan = await action(client, user, await create(client, user), 'confirm')
    now = datetime.now(timezone.utc)
    past = MonitoringEvent(patient_id=user.id, plan_id=plan['id'], event_type='follow_up_reminder', scheduled_at=now-timedelta(minutes=1))
    future = MonitoringEvent(patient_id=user.id, plan_id=plan['id'], event_type='follow_up_reminder', scheduled_at=now+timedelta(days=1))
    db_session.add_all([past, future])
    await db_session.commit()
    paused = await action(client, user, plan, 'pause')
    await db_session.refresh(past)
    assert 'paused' == past.status
    assert 409 == (await client.post(f'/api/v1/patient/care-plans/{plan["id"]}/ack?task_id={plan["tasks"][0]["id"]}', headers=headers(user))).status_code
    await db_session.commit()
    resumed = await action(client, user, paused, 'resume')
    await db_session.refresh(past)
    await db_session.refresh(future)
    assert 'cancelled' == past.status and 'pending' == future.status
    cancelled = await action(client, user, resumed, 'cancel')
    await db_session.refresh(future)
    assert 'cancelled' == future.status and 'cancelled' == cancelled['status']
    # 遗留 pending 漏网事件及已投递 ETA 也受发送前计划检查约束。
    leak = MonitoringEvent(patient_id=user.id, plan_id=plan['id'], event_type='follow_up_reminder', scheduled_at=now)
    db_session.add(leak)
    await db_session.commit()
    calls = []
    async def send(*args): calls.append(args)
    monkeypatch.setattr(monitoring, '_send_reminder_email', send)
    outcome = await monitoring._claim_and_send(str(leak.id), async_sessionmaker(test_engine, expire_on_commit=False))
    assert 'skipped' == outcome and [] == calls
    await db_session.refresh(leak)
    assert 'cancelled' == leak.status


@pytest.mark.asyncio
@pytest.mark.parametrize('shape', ['list', 'dict'])
async def test_legacy_shapes_stable_ids_and_persistence(client, db_session, shape):
    user = await patient(db_session)
    tasks = [{'description': '历史任务无ID'}, {'id': 'historical-id', 'description': '历史任务有ID'}]
    plan = CarePlan(patient_id=user.id, title='旧计划', status='active', tasks=tasks if shape=='list' else {'tasks': tasks})
    db_session.add(plan)
    await db_session.commit()
    url = f'/api/v1/patient/care-plans/{plan.id}'
    first = (await client.get(url, headers=headers(user))).json()
    second = (await client.get(url, headers=headers(user))).json()
    assert first == second and 'legacy_record' == first['source_type'] and first['confirmed_at'] is None
    result = await client.post(url+'/ack?task_id='+first['tasks'][0]['id'], headers=headers(user))
    assert 200 == result.status_code
    await db_session.refresh(plan)
    assert 'completed' == plan.tasks['tasks'][0]['status'] and 50 == plan.progress_percent


@pytest.mark.asyncio
async def test_dates_expiry_and_values(client, db_session):
    user = await patient(db_session)
    future_date = (today()+timedelta(days=1)).isoformat()
    plan = await action(client, user, await create(client, user, start_date=future_date,
        tasks=[{'description':'明日事项','due_date':future_date}]), 'confirm')
    assert not plan['can_execute']
    assert 409 == (await client.post(f'/api/v1/patient/care-plans/{plan["id"]}/ack?task_id={plan["tasks"][0]["id"]}', headers=headers(user))).status_code
    await db_session.commit()
    expired = CarePlan(patient_id=user.id, title='逾期旧计划', status='active', end_date=today()-timedelta(days=1), tasks=[{'id':'old','due_date':'2000-01-01'}])
    db_session.add(expired)
    await db_session.commit()
    response = await client.get('/api/v1/patient/care-plans?status=expired', headers=headers(user))
    assert [str(expired.id)] == [p['id'] for p in response.json()]
    assert 'expired' == response.json()[0]['effective_status']
    assert response.json()[0]['tasks'][0]['is_overdue']
    plan = await action(client, user, await create(client, user), 'confirm')
    for value in [True, 'NaN', 'Infinity']:
        response = await client.post('/api/v1/patient/check-in', headers=headers(user), json={
            'plan_id':plan['id'], 'task_id':plan['tasks'][1]['id'], 'value':value})
        assert 422 == response.status_code
    response = await client.post('/api/v1/patient/check-in', headers=headers(user), json={
        'plan_id':plan['id'], 'task_id':plan['tasks'][0]['id'], 'value':123})
    assert 422 == response.status_code


@pytest.mark.asyncio
async def test_keyset_pagination_same_timestamp_without_leaks(client, db_session):
    user, other = await patient(db_session), await patient(db_session)
    stamp = datetime.now(timezone.utc)
    plans = [CarePlan(patient_id=user.id, title=f'计划{i}', tasks={}, created_at=stamp) for i in range(13)]
    db_session.add_all(plans+[CarePlan(patient_id=other.id, title='不得泄露', tasks={}, created_at=stamp)])
    await db_session.commit()
    seen, cursor = [], None
    while True:
        params = {'include_page': 'true', 'limit': 5}
        if cursor: params.update(cursor_at=cursor['created_at'],cursor_id=cursor['id'])
        response = await client.get('/api/v1/patient/care-plans', headers=headers(user), params=params)
        assert 200 == response.status_code
        data = response.json()
        seen += [p['id'] for p in data['items']]
        cursor = data['next_cursor']
        if not cursor: break
    assert 13 == len(seen) == len(set(seen)) and {str(p.id) for p in plans} == set(seen)
    assert 422 == (await client.get('/api/v1/patient/care-plans?cursor_id='+str(uuid4()), headers=headers(user))).status_code


@pytest.mark.asyncio
async def test_concurrent_create_and_different_task_completion(test_engine, db_session):
    user = await patient(db_session)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def fresh_db():
        async with factory() as db: yield db
    app.dependency_overrides[get_db] = fresh_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as api:
            data = payload()
            results = await asyncio.gather(*[api.post('/api/v1/patient/care-plans',headers=headers(user),json=data) for _ in range(2)])
            assert [201,201] == [r.status_code for r in results]
            assert results[0].json() == results[1].json()
            plan = await action(api, user, results[0].json(), 'confirm')
            results = await asyncio.gather(*[api.post(f'/api/v1/patient/care-plans/{plan["id"]}/ack?task_id={t["id"]}',headers=headers(user)) for t in plan['tasks']])
            assert [200,200] == [r.status_code for r in results]
            recovered = (await api.get(f'/api/v1/patient/care-plans/{plan["id"]}',headers=headers(user))).json()
            assert 100 == recovered['progress_percent'] and 'completed' == recovered['status']
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize('templated', [False, True])
async def test_email_false_return_is_not_success(monkeypatch, templated):
    class Result:
        def scalar_one_or_none(self):
            return SimpleNamespace() if templated else None
    class Session:
        async def execute(self, stmt): return Result()
    async def failed_delivery(**kwargs): return False, '合成SMTP拒绝', None
    monkeypatch.setattr(monitoring.email_service, 'send_email', failed_delivery)
    monkeypatch.setattr(monitoring.email_service, 'send_templated_email', failed_delivery)
    evt=SimpleNamespace(payload={'email':'synthetic@example.invalid','description':'合成事项'},
                        event_type='follow_up_reminder',scheduled_at=datetime.now(timezone.utc))
    with pytest.raises(RuntimeError, match='合成SMTP拒绝'):
        await monitoring._send_reminder_email(Session(),evt)
