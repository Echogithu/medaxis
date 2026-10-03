"""真实认证、PostgreSQL JSONB 保存、版本冲突与档案下游读取。"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentSession, AgentSessionType, PatientHealthProfile
from app.models.user import User, UserRole, UserStatus
from app.services.case_preparation import build_package, build_source_snapshot, preparation_fingerprint
from app.api.v1.agents import _load_health_profile_context, _patient_history_with_profile, _build_chat_context


async def patient(db, label="档案合成患者"):
    user = User(email=f"profile-{uuid4()}@example.invalid", full_name=label,
                hashed_password="unused", role=UserRole.PATIENT, status=UserStatus.ACTIVE)
    db.add(user)
    await db.commit()
    return user


def headers(user, **kwargs):
    return {"Authorization": f"Bearer {create_access_token(str(user.id), platform='web', **kwargs)}"}


@pytest.mark.asyncio
async def test_profile_roundtrip_sources_states_and_unchanged_timestamps(client, db_session):
    user = await patient(db_session)
    auth = headers(user)
    initial = await client.get('/api/v1/patient/profile', headers=auth)
    assert initial.status_code == 200
    assert initial.json()['section_states'] == dict.fromkeys(['allergies', 'conditions', 'medications'], 'not_recorded')
    data = {
        'expected_revision': 0, 'height': 170, 'weight': 65, 'allergies': [],
        'section_states': {'allergies': 'unknown', 'conditions': 'present', 'medications': 'present'},
        'chronic_diseases': [
            {'name': '合成慢性病', 'category': 'chronic'},
            {'name': '合成特殊疾病', 'category': 'special', 'severity': 'severe',
             'diagnosed_date': '2020-01-02', 'notes': '患者自报说明', 'source': 'doctor_verified', 'updated_at': '2000-01-01'},
        ],
        'medications': [{'name': '合成有效药', 'status': 'active'}, {'name': '合成停用药', 'status': 'stopped'}],
    }
    saved = await client.patch('/api/v1/patient/profile', headers=auth, json=data)
    assert saved.status_code == 200, saved.text
    record = saved.json()
    assert record['revision'] == 1 and record['updated_at']
    special = record['chronic_diseases'][1]
    assert special['source'] == 'patient_reported'
    assert special['updated_at'] != '2000-01-01'
    assert special['category'] == 'special' and special['severity'] == 'severe'
    assert special['diagnosed_date'] == '2020-01-02' and special['notes'] == '患者自报说明'
    assert (await client.get('/api/v1/patient/profile', headers=auth)).json() == record
    repeat = await client.patch('/api/v1/patient/profile', headers=auth, json={
        'expected_revision': 1, 'name': '修改基础姓名', 'chronic_diseases': record['chronic_diseases'],
    })
    assert repeat.status_code == 200
    assert repeat.json()['chronic_diseases'][1]['updated_at'] == special['updated_at']
    assert repeat.json()['section_metadata']['conditions'] == record['section_metadata']['conditions']
    cleared = await client.patch('/api/v1/patient/profile', headers=auth, json={
        'expected_revision': 2, 'height': None, 'gender': None,
        'section_states': {'allergies': 'none'},
    })
    assert cleared.status_code == 200
    assert cleared.json()['height'] is None and cleared.json()['gender'] is None
    assert cleared.json()['section_states']['allergies'] == 'none'


@pytest.mark.asyncio
async def test_profile_rejects_stale_invalid_and_unauthorized_updates(client, db_session):
    user = await patient(db_session)
    auth = headers(user)
    expired = headers(user, expires_delta=timedelta(seconds=-1))
    assert (await client.patch('/api/v1/patient/profile', headers=auth, json={'expected_revision': 0, 'allergies': ['合成过敏源']})).status_code == 200
    for payload, expected in [
        ({'expected_revision': 0, 'allergies': []}, 409),
        ({'allergies': []}, 428),
        ({'expected_revision': 1, 'allergies': ['合成过敏源'], 'section_states': {'allergies': 'none'}}, 422),
        ({'expected_revision': 1, 'chronic_diseases': [{'name': '疾病', 'severity': 'invalid'}]}, 422),
        ({'expected_revision': 1, 'chronic_diseases': [{'name': '疾病', 'diagnosed_date': '2999-01-01'}]}, 422),
        ({'expected_revision': 1, 'name': None}, 422),
        ({'expected_revision': 1, 'medications': None}, 422),
    ]:
        response = await client.patch('/api/v1/patient/profile', headers=auth, json=payload)
        assert response.status_code == expected, response.text
        await db_session.rollback()
    assert (await client.get('/api/v1/patient/profile', headers=auth)).json()['allergies'] == ['合成过敏源']
    assert (await client.get('/api/v1/patient/profile')).status_code == 401
    assert (await client.patch('/api/v1/patient/profile', headers=expired, json={'expected_revision': 1})).status_code == 401


@pytest.mark.asyncio
async def test_legacy_profile_and_patient_isolation_and_downstream(client, db_session, monkeypatch):
    user, other = await patient(db_session), await patient(db_session, '另一患者')
    profile = PatientHealthProfile(patient_id=user.id, allergies=[],
        chronic_diseases=[{'code': 'I10', 'name': '历史合成慢性病'}],
        current_medications=[{'name': '历史有效药'}, {'name': '历史停用药', 'status': 'stopped'}],
        record_metadata={}, health_summary='不应进入档案上下文的AI画像')
    db_session.add(profile)
    await db_session.commit()
    response = (await client.get('/api/v1/patient/profile', headers=headers(user))).json()
    assert response['revision'] == 0 and response['updated_at'] is None
    assert response['chronic_diseases'][0]['category'] == 'chronic'
    assert response['chronic_diseases'][0]['severity'] == 'unknown'
    assert response['chronic_diseases'][0]['source'] == 'legacy_record'
    assert response['chronic_diseases'][0]['updated_at'] is None
    assert (await client.get('/api/v1/patient/profile', headers=headers(other))).json()['chronic_diseases'] == []
    combined = await _patient_history_with_profile(db_session, str(user.id), '本次合成症状')
    assert '历史合成慢性病' in combined and '本次合成症状' in combined
    assert '不应进入档案上下文的AI画像' not in combined
    assert '历史停用药' not in combined.split('已停用药物')[0]
    assert await _load_health_profile_context(db_session, None) == ''
    parent = AgentSession(user_id=user.id, session_type=AgentSessionType.DIAGNOSIS, context={}, structured_output={})
    db_session.add(parent)
    await db_session.commit()
    from app.tools.medical import QueryPatientHistoryTool
    from unittest.mock import AsyncMock
    monkeypatch.setattr(QueryPatientHistoryTool, 'execute', AsyncMock(return_value={'cases': []}))
    chat_context = await _build_chat_context(db_session, parent, str(user.id))
    assert '历史合成慢性病' in chat_context and '已停用药物' in chat_context
    case = SimpleNamespace(id=uuid4(), title='合成病例', chief_complaint='头痛', ai_diagnosis_summary=None, severity=None, is_emergency=False)
    snapshot = build_source_snapshot(case, parent, [], profile)
    assert [item['name'] for item in snapshot['patient_profile']['current_medications']] == ['历史有效药']
    assert [item['name'] for item in snapshot['patient_profile']['stopped_medications']] == ['历史停用药']
    before = preparation_fingerprint(snapshot, [])
    legacy_package = build_package(snapshot, [])
    legacy_fact = next(item for item in legacy_package['known_facts'] if item['id'] == 'patient.profile.chronic_diseases')
    assert legacy_fact['source_type'] == 'legacy_record'
    assert '严重程度：未知' in legacy_fact['display_value'] and '来源未记录' in legacy_fact['display_value']
    assert '"category"' not in legacy_fact['display_value']
    saved = await client.patch('/api/v1/patient/profile', headers=headers(user), json={
        'expected_revision': 0, 'section_states': {'allergies': 'none'},
    })
    assert saved.status_code == 200
    await db_session.refresh(profile)
    source = build_source_snapshot(case, parent, [], profile)
    assert before != preparation_fingerprint(source, [])
    package = build_package(source, [])
    assert not any(item['id'] == 'unknown.allergies' for item in package['unknown_facts'])
    assert any(item['id'] == 'patient.profile.allergies' and '明确自报无' in item['value'] for item in package['known_facts'])
    assert next(item for item in package['known_facts'] if item['id'] == 'patient.profile.allergies')['assertion_status'] == 'denied'
    assert any(item['id'] == 'patient_profile.allergies' for item in package['source_index'])


@pytest.mark.asyncio
async def test_concurrent_first_save_has_one_winner_and_one_conflict(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as seed:
        user = await patient(seed)
        auth = headers(user)
    async def independent_db():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = independent_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as api:
            responses = await asyncio.gather(*[
                api.patch('/api/v1/patient/profile', headers=auth, json={'expected_revision': 0, 'allergies': [name]})
                for name in ['并发合成甲', '并发合成乙']
            ])
            assert sorted(item.status_code for item in responses) == [200, 409]
            winner = next(item.json() for item in responses if item.status_code == 200)
            recovered = await api.get('/api/v1/patient/profile', headers=auth)
            assert recovered.json()['allergies'] == winner['allergies']
        async with factory() as db:
            profiles = (await db.scalars(select(PatientHealthProfile).where(PatientHealthProfile.patient_id == user.id))).all()
            assert len(profiles) == 1 and profiles[0].record_metadata['revision'] == 1
    finally:
        app.dependency_overrides.clear()
