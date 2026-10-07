"""本人引用的真实API/数据库：固定版本、并发、删病例与权限。"""
import asyncio
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.medical_case import CaseStatus, MedicalCase
from app.models.patient_report import PatientReport, ReportCaseLink, ReportManagementOperation, ReportProcessingJob
from app.models.user import UserRole
from tests.test_patient_care_plans import headers, patient
from tests.test_report_review import client, setup, save as save_review, confirm


async def case(db, user, title='合成本人病例', **changes):
    item = MedicalCase(patient_id=user.id, title=title, status=CaseStatus.PENDING_REVIEW, **changes)
    db.add(item); await db.commit(); return item


async def state(api, url, auth):
    response = await api.get(url+'/case-links', headers=auth)
    assert 200 == response.status_code, response.text
    return response.json()


def body(view, ids, **changes):
    return {'request_id': str(uuid4()), 'expected_links_revision': view['links_revision'],
        'expected_review_revision': view['review_revision'], 'expected_source_hash': view['source_hash'],
        'case_ids': [str(item) for item in ids], 'refresh_case_ids': []} | changes


async def save(api, url, auth, data):
    response = await api.post(url+'/case-links', headers=auth, json=data)
    assert 200 == response.status_code, response.text
    return response.json()


@pytest.mark.asyncio
async def test_multiple_own_links_preserve_pins_and_explicit_refresh(client, db_session, test_engine):
    user, report, url, auth = await setup(client, db_session)
    first, second = await case(db_session, user), await case(db_session, user, '合成已归档病例')
    second.status = CaseStatus.ARCHIVED; await db_session.commit()
    before = await state(client, url, auth)
    data = body(before, [first.id, second.id]); linked = await save(client, url, auth, data)
    assert 2 == len(linked['workspace']['items']) and 1 == linked['workspace']['links_revision']
    assert {'unverified'} == {item['status'] for item in linked['workspace']['items']}
    await save_review(client, url, auth); confirmed, _ = await confirm(client, url, auth)
    view = await state(client, url, auth)
    assert {'review_changed'} == {item['status'] for item in view['items']}
    updated = await save(client, url, auth, body(view, [first.id, second.id], refresh_case_ids=[str(first.id)]))
    by_id = {item['case_id']: item for item in updated['workspace']['items']}
    assert confirmed['version']['id'] == by_id[str(first.id)]['review_version_id']
    assert 'patient_confirmed' == by_id[str(first.id)]['status'] and by_id[str(second.id)]['review_version_id'] is None
    assert 'review_changed' == by_id[str(second.id)]['status']
    await save_review(client, url, auth)
    after = {item['case_id']: item for item in (await state(client, url, auth))['items']}
    assert 'review_changed' == after[str(first.id)]['status']
    assert confirmed['version']['id'] == after[str(first.id)]['review_version_id']
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        row = await db.get(PatientReport, UUID(report['id']))
        assert 'workflow' not in row.__dict__
        assert 0 == await db.scalar(select(func.count()).select_from(ReportProcessingJob).where(ReportProcessingJob.report_id == row.id))


@pytest.mark.asyncio
async def test_replay_never_resurrects_removed_links_and_concurrent_atomic_writes(client, db_session, test_engine):
    user, _, url, auth = await setup(client, db_session)
    first, second = await case(db_session, user), await case(db_session, user)
    initial = await state(client, url, auth); data = body(initial, [first.id, second.id])
    replies = await asyncio.gather(*(client.post(url+'/case-links', headers=auth, json=data) for _ in range(2)))
    assert [200,200] == [item.status_code for item in replies]
    assert replies[0].json()['operation']['id'] == replies[1].json()['operation']['id']
    assert 409 == (await client.post(url+'/case-links', headers=auth, json=data | {'case_ids': []})).status_code
    assert 409 == (await client.post(url+'/case-links', headers=auth, json=body(initial, [first.id]))).status_code
    removed = await save(client, url, auth, body(await state(client, url, auth), []))
    assert [] == removed['workspace']['items']
    replay = await save(client, url, auth, data)
    assert [] == replay['workspace']['items'] and 2 == replay['workspace']['links_revision']
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as db:
        report_id = UUID(url.split('/')[-1])
        assert 2 == await db.scalar(select(func.count()).select_from(ReportManagementOperation).where(ReportManagementOperation.report_id == report_id))
        assert 0 == await db.scalar(select(func.count()).select_from(ReportCaseLink).where(ReportCaseLink.report_id == report_id))


@pytest.mark.asyncio
async def test_case_delete_cascade_keeps_report_originals_and_old_submit_cannot_restore(client, db_session):
    user, report, url, auth = await setup(client, db_session)
    first = await case(db_session, user, treatment_plan={'synthetic': '原治疗安排'})
    data = body(await state(client, url, auth), [first.id]); await save(client, url, auth, data)
    case_url = '/api/v1/patient/cases/'+str(first.id)+'/reports'
    listing = (await client.get(case_url, headers=auth)).json()
    assert report['id'] == listing['items'][0]['id'] and 'unverified' == listing['items'][0]['link']['status']
    original = await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)
    assert 204 == (await client.delete('/api/v1/medical-cases/'+str(first.id), headers=auth)).status_code
    assert [] == (await state(client, url, auth))['items']
    assert [] == (await save(client, url, auth, data))['workspace']['items']
    assert original.content == (await client.get(url+'/files/'+report['files'][0]['id'], headers=auth)).content
    assert 404 == (await client.get(case_url, headers=auth)).status_code
    assert 404 == (await client.post(url+'/case-links', headers=auth, json=body(await state(client, url, auth), [first.id]))).status_code


@pytest.mark.asyncio
async def test_source_conflict_options_paging_and_dual_account_doctor_denied(client, db_session):
    user, report, url, auth = await setup(client, db_session)
    other, doctor = await patient(db_session), await patient(db_session)
    doctor.role = UserRole.DOCTOR; await db_session.commit()
    own = await case(db_session, user, '合成A病例', assigned_doctor_id=doctor.id)
    second = await case(db_session, user, '合成B病例'); foreign = await case(db_session, other)
    view = await state(client, url, auth)
    assert 404 == (await client.post(url+'/case-links', headers=auth, json=body(view, [own.id, foreign.id]))).status_code
    assert [] == (await state(client, url, auth))['items']
    assert 422 == (await client.post(url+'/case-links', headers=auth, json=body(view,[own.id,own.id]))).status_code
    assert 422 == (await client.post(url+'/case-links', headers=auth, json=body(view,[own.id],refresh_case_ids=[str(second.id)]))).status_code
    options = (await client.get(url+'/case-options?limit=1&page=1', headers=auth)).json()
    options2 = (await client.get(url+'/case-options?limit=1&page=2', headers=auth)).json()
    assert 2 == options['total'] and options['items'][0]['id'] != options2['items'][0]['id']
    assert 1 == (await client.get(url+'/case-options?search=合成A', headers=auth)).json()['total']
    await save(client, url, auth, body(view,[own.id]))
    old = await state(client, url, auth)
    fields = {key:report[key] for key in ['title','category','institution','examination_date','report_date','notes']}
    assert 200 == (await client.patch(url,headers=auth,json=fields|{'expected_revision':0,'category':'other'})).status_code
    assert 'source_changed' == (await state(client,url,auth))['items'][0]['status']
    assert 409 == (await client.post(url+'/case-links',headers=auth,json=body(old,[own.id]))).status_code
    for suffix in ['/case-links','/case-options']:
        assert 404 == (await client.get(url+suffix,headers=headers(other))).status_code
        assert 403 == (await client.get(url+suffix,headers=headers(doctor))).status_code
        assert 401 == (await client.get(url+suffix)).status_code
    case_url='/api/v1/patient/cases/'+str(own.id)+'/reports'
    assert 404 == (await client.get(case_url,headers=headers(other))).status_code
    assert 403 == (await client.get(case_url,headers=headers(doctor))).status_code
    assert 404 == (await client.post(url+'/case-links',headers=headers(other),json=body(old,[]))).status_code
    assert 403 == (await client.post(url+'/case-links',headers=headers(doctor),json=body(old,[]))).status_code
    # 新引用从不进入既有医生材料/会话输出。
    detail = await client.get('/api/v1/doctor/cases/'+str(own.id),headers=headers(doctor))
    assert 200 == detail.status_code,detail.text
    assert report['id'] not in detail.text
