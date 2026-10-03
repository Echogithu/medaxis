"""真实数据库核验指标隔离、去重、分页及输入边界。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from app.core.security import create_access_token
from app.models.user import User, UserRole, UserStatus


async def actor(db, role=UserRole.PATIENT):
    user = User(email=f'{uuid4()}@example.com', full_name='指标合成患者', hashed_password='unused', role=role, status=UserStatus.ACTIVE)
    db.add(user)
    await db.commit()
    return {'Authorization': 'Bearer ' + create_access_token(str(user.id), platform='web')}


def fields(**changes):
    return {'request_id': str(uuid4()), 'systolic': 128, 'diastolic': 82, 'heart_rate': 68,
            'weight': 62.5, 'recorded_at': (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), **changes}


@pytest.mark.asyncio
async def test_measurements_persist_isolate_and_deduplicate(client, db_session):
    own, other = await actor(db_session), await actor(db_session)
    payload = fields()
    first = await client.post('/api/v1/patient/measurements', headers=own, json=payload)
    assert 201 == first.status_code, first.text
    assert 62.5 == first.json()['weight']
    assert 'patient_reported' == first.json()['source']
    repeat = await client.post('/api/v1/patient/measurements', headers=own, json=payload)
    assert first.json() == repeat.json()
    assert 409 == (await client.post('/api/v1/patient/measurements', headers=own, json={**payload, 'weight': 63.2})).status_code
    assert 409 == (await client.post('/api/v1/patient/measurements', headers=other, json=payload)).status_code
    assert [] == (await client.get('/api/v1/patient/measurements', headers=other)).json()['items']
    newer = fields(recorded_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    assert 201 == (await client.post('/api/v1/patient/measurements', headers=own, json=newer)).status_code
    page = (await client.get('/api/v1/patient/measurements?limit=1', headers=own)).json()
    assert newer['request_id'] == page['items'][0]['id'] and page['has_more']
    assert payload['request_id'] == (await client.get('/api/v1/patient/measurements?limit=1&page=2', headers=own)).json()['items'][0]['id']
    profile = (await client.get('/api/v1/patient/profile', headers=own)).json()
    assert profile['weight'] is None and profile['revision'] == 0


@pytest.mark.asyncio
async def test_measurement_input_and_role_boundaries(client, db_session):
    own = await actor(db_session)
    doctor = await actor(db_session, UserRole.DOCTOR)
    assert 401 == (await client.get('/api/v1/patient/measurements')).status_code
    assert 403 == (await client.get('/api/v1/patient/measurements', headers=doctor)).status_code
    assert 403 == (await client.post('/api/v1/patient/measurements', headers=doctor, json=fields())).status_code
    for change in [dict(systolic=70, diastolic=80), dict(diastolic=None), dict(systolic=None, diastolic=None, heart_rate=None, weight=None),
                   dict(weight=-1), dict(heart_rate=True), dict(systolic=128.5), dict(recorded_at='2026-01-01T10:00:00'),
                   dict(recorded_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()), dict(patient_id=str(uuid4()))]:
        response = await client.post('/api/v1/patient/measurements', headers=own, json=fields(**change))
        assert 422 == response.status_code, response.text
    assert 422 == (await client.get('/api/v1/patient/measurements?limit=51', headers=own)).status_code
    assert 201 == (await client.post('/api/v1/patient/measurements', headers=own, json=fields(systolic=None, diastolic=None, heart_rate=None))).status_code
