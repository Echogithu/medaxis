"""独立报告真实 API/数据库：原件、类型、恢复、并发和患者权限。"""
import asyncio
import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_db
from app.main import app
from app.models.document_parse import DocumentParseTask
from app.models.patient_report import PatientReport, PatientReportFile
from app.models.user import UserRole
from tests.report_samples import sample_image, text_pdf
from tests.test_patient_care_plans import headers, patient

BASE = '/api/v1/patient/reports'


def metadata(**changes):
    return dict(title='独立合成检查报告', category='lab', institution='', examination_date=None,
                report_date=None, notes='', ownership_declared=True, request_id=str(uuid4())) | changes


def multipart(data, files=None):
    files = files if files is not None else [('合成报告.png', sample_image(), 'image/png')]
    return {'data': {'metadata': json.dumps(data, ensure_ascii=False)},
            'files': [('files', file) for file in files]}


async def create(client, user, data=None, files=None):
    response = await client.post(BASE, headers=headers(user), **multipart(data or metadata(), files))
    assert 201 == response.status_code, response.text
    return response.json()


@pytest.mark.asyncio
async def test_independent_archive_originals_counts_persistence_and_no_old_parse(client, db_session, test_engine):
    user = await patient(db_session)
    image, pdf = sample_image(), text_pdf(count=2)
    report = await create(client, user, files=[('原件.png', image, 'image/png'), ('多页.pdf', pdf, 'application/pdf')])
    assert 2 == report['file_count'] and 3 == report['page_count']
    assert [0, 1] == [file['position'] for file in report['files']]
    assert ['原件.png', '多页.pdf'] == [file['filename'] for file in report['files']]
    assert 'patient_upload' == report['source'] and 'not_started' == report['extraction_status']
    assert 'unverified' == report['review_status'] and report['examination_date'] is None
    assert 0 == await db_session.scalar(select(func.count()).select_from(DocumentParseTask))
    assert all('content' not in file and 'sha256' not in file for file in report['files'])
    listing = (await client.get(BASE, headers=headers(user))).json()
    assert {'archived': 1, 'pending_review': 1, 'latest_examination_date': None, 'trashed': 0} == listing['stats']
    for index, expected in enumerate([image, pdf]):
        result = await client.get(f'{BASE}/{report["id"]}/files/{report["files"][index]["id"]}', headers=headers(user))
        assert expected == result.content
        assert 'private, no-store' == result.headers['cache-control']
        assert 'nosniff' == result.headers['x-content-type-options']
        assert "attachment; filename*=UTF-8''" in result.headers['content-disposition']
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as fresh:
        row = await fresh.get(PatientReport, report['id'])
        assert '独立合成检查报告' == row.title
        file = await fresh.scalar(select(PatientReportFile).where(PatientReportFile.report_id == row.id))
        assert 'content' not in file.__dict__


@pytest.mark.asyncio
async def test_dual_account_every_archive_route_and_wrong_role(client, db_session):
    owner, other = await patient(db_session), await patient(db_session)
    report = await create(client, owner)
    url = f'{BASE}/{report["id"]}'
    edit = metadata(title='越权修改'); edit.pop('request_id'); edit.pop('ownership_declared'); edit['expected_revision'] = 0
    assert 404 == (await client.get(url, headers=headers(other))).status_code
    assert 404 == (await client.get(url+'/files/'+report['files'][0]['id'], headers=headers(other))).status_code
    assert 404 == (await client.patch(url, headers=headers(other), json=edit)).status_code
    assert [] == (await client.get(BASE, headers=headers(other))).json()['items']
    assert 404 == (await client.get(url+'/files/'+str(uuid4()), headers=headers(owner))).status_code
    assert 401 == (await client.get(BASE)).status_code
    assert 401 == (await client.post(BASE, **multipart(metadata()))).status_code
    await db_session.commit()
    other.role = UserRole.DOCTOR
    await db_session.commit()
    for method, path, kwargs in [('get', BASE, {}), ('get', url, {}), ('get', url+'/files/'+report['files'][0]['id'], {}),
                                  ('post', BASE, multipart(metadata())), ('patch', url, {'json': edit})]:
        assert 403 == (await getattr(client, method)(path, headers=headers(other), **kwargs)).status_code


@pytest.mark.asyncio
async def test_replay_response_loss_and_changed_request_rejected(client, db_session):
    user = await patient(db_session)
    data, image = metadata(), sample_image()
    first = await create(client, user, data, [('a.png', image, 'image/png')])
    repeated = await create(client, user, data, [('a.png', image, 'image/png')])
    assert first == repeated
    response = await client.post(BASE, headers=headers(user), **multipart(data | {'title': '已改变'}, [('a.png', image, 'image/png')]))
    assert 409 == response.status_code
    assert 1 == (await client.get(BASE, headers=headers(user))).json()['total']


@pytest.mark.asyncio
async def test_metadata_edit_conflict_dates_and_source_stability(client, db_session):
    user = await patient(db_session)
    original = await create(client, user)
    url = BASE+'/'+original['id']
    edit = dict(title='本人修正名称', category='imaging', institution='合成医院', examination_date='2026-09-20',
                report_date=None, notes='按原件补充', expected_revision=0)
    response = await client.patch(url, headers=headers(user), json=edit)
    assert 200 == response.status_code
    updated = response.json()
    assert 1 == updated['revision'] and 1 == updated['source_version']
    assert original['files'] == updated['files']
    assert original['created_at'] == updated['created_at']
    assert updated['updated_at'] >= original['updated_at']
    assert 409 == (await client.patch(url, headers=headers(user), json=edit)).status_code
    assert '本人修正名称' == (await client.get(url, headers=headers(user))).json()['title']
    for bad in [edit | {'expected_revision': True}, edit | {'examination_date': 0}, edit | {'category': 'diagnosed'},
                edit | {'title': ' '}, edit | {'doctor_verified': True}, edit | {'report_date': '2026-02-30'}]:
        assert 422 == (await client.patch(url, headers=headers(user), json=bad)).status_code


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['empty', 'wrong_magic', 'mime', 'corrupt', 'encrypted', 'file_count', 'page_total', 'ownership', 'fields'], ids=str)
async def test_bad_upload_atomic_rejection(client, db_session, case):
    user = await patient(db_session)
    original_file_count = await db_session.scalar(select(func.count()).select_from(PatientReportFile))
    data, files = metadata(), None
    if case == 'empty': files = [('a.png', b'', 'image/png')]
    if case == 'wrong_magic': files = [('a.pdf', sample_image(), 'application/pdf')]
    if case == 'mime': files = [('a.png', sample_image(), 'text/html')]
    if case == 'corrupt': files = [('a.png', b'\x89PNG\r\n\x1a\ninvalid', 'image/png')]
    if case == 'encrypted': files = [('a.pdf', text_pdf(encrypted=True), 'application/pdf')]
    if case == 'file_count': files = [('a.png', sample_image(), 'image/png')] * 6
    if case == 'page_total': files = [('20.pdf', text_pdf(count=20), 'application/pdf'), ('extra.png', sample_image(), 'image/png')]
    if case == 'ownership': data['ownership_declared'] = 1
    if case == 'fields': data['doctor_verified'] = True
    response = await client.post(BASE, headers=headers(user), **multipart(data, files))
    assert 422 == response.status_code
    assert 0 == (await client.get(BASE, headers=headers(user))).json()['total']
    assert original_file_count == await db_session.scalar(select(func.count()).select_from(PatientReportFile))


@pytest.mark.asyncio
async def test_search_literal_dates_category_stats_pagination_without_bytes(client, db_session):
    owner, other = await patient(db_session), await patient(db_session)
    stamp = datetime.now(timezone.utc)
    for index in range(13):
        data = metadata(title=f'同时间报告{index}' + ('百分号%_' if index == 1 else ''),
                        category='imaging' if index == 1 else 'lab', institution='北方合成医院',
                        examination_date=date(2026, 9, 30) if index == 1 else None)
        # 分页验证只播种元数据；真实原件链路由独立上传用例覆盖。
        db_session.add(PatientReport(patient_id=owner.id, request_fingerprint='0'*64, content_hash='1'*64,
                                    **data, created_at=stamp, updated_at=stamp))
    db_session.add(PatientReport(patient_id=other.id, **metadata(title='禁止泄漏'), request_fingerprint='0'*64, content_hash='2'*64))
    await db_session.commit()
    seen = []
    for page in range(1, 4):
        response = await client.get(BASE, headers=headers(owner), params={'page': page, 'limit': 5})
        assert 200 == response.status_code
        data = response.json(); seen.extend(report['id'] for report in data['items'])
        assert 13 == data['total'] == data['stats']['archived']
        assert '2026-09-30' == data['stats']['latest_examination_date']
    assert 13 == len(seen) == len(set(seen))
    for search, expected in [('%_', 1), ('2026-09-30', 1), ('北方', 13), ('禁止泄漏', 0)]:
        result = (await client.get(BASE, headers=headers(owner), params={'search': search})).json()
        assert expected == result['total']
    assert 1 == (await client.get(BASE, headers=headers(owner), params={'category': 'imaging', 'pending_only': True})).json()['total']
    for params in [{'page': 0}, {'limit': 100}, {'category': 'fake'}, {'search': 'x'*201}]:
        assert 422 == (await client.get(BASE, headers=headers(owner), params=params)).status_code


@pytest.mark.asyncio
async def test_concurrent_same_submission_returns_one_archive(test_engine, db_session):
    user = await patient(db_session)
    data, image = metadata(), sample_image()
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def fresh_db():
        async with factory() as db: yield db
    app.dependency_overrides[get_db] = fresh_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as api:
            responses = await asyncio.gather(*[api.post(BASE, headers=headers(user), **multipart(data, [('a.png', image, 'image/png')])) for _ in range(2)])
            assert [201, 201] == [response.status_code for response in responses]
            assert responses[0].json() == responses[1].json()
            assert 1 == (await api.get(BASE, headers=headers(user))).json()['total']
    finally:
        app.dependency_overrides.clear()
