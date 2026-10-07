"""重复原件只由患者选择；真实数据库证明不覆盖、幂等和本人隔离。"""
import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import get_db
from app.main import app
from app.models.patient_report import PatientReport, ReportUploadSubmission
from tests.report_samples import sample_image, text_pdf
from tests.test_patient_care_plans import headers, patient
from tests.test_patient_reports import BASE, create, metadata, multipart
from tests.test_report_review import client, save as save_review, confirm
from tests.test_report_links import case, state as link_state, body as link_body, save as save_links


@pytest.mark.asyncio
async def test_duplicate_prompt_reuse_preserves_existing_and_separate_replays(client, db_session):
    user = await patient(db_session)
    first = await create(client, user, metadata(title='保留原名称', examination_date='2026-09-20', notes='原备注'))
    url, auth = BASE+'/'+first['id'], headers(user)
    await save_review(client, url, auth)
    await confirm(client, url, auth)
    linked_case = await case(db_session, user)
    await save_links(client, url, auth, link_body(await link_state(client, url, auth), [linked_case.id]))
    first = (await client.get(url, headers=auth)).json()
    before_review = (await client.get(url+'/review', headers=auth)).json()
    before_links = await link_state(client, url, auth)
    data = metadata(title='新名称不能覆盖', category='imaging', notes='不同备注')
    duplicate = await client.post(BASE, headers=headers(user), **multipart(data))
    assert 409 == duplicate.status_code
    detail = duplicate.json()['detail']
    assert 'duplicate_report' == detail['code']
    assert [first['id']] == [item['id'] for item in detail['reports']]
    assert {'id', 'title', 'category', 'institution', 'examination_date', 'report_date', 'created_at'} == set(detail['reports'][0])
    assert 1 == (await client.get(BASE, headers=headers(user))).json()['stats']['archived']
    reuse = data | {'request_id': str(uuid4()), 'duplicate_mode': 'reuse', 'duplicate_report_id': first['id']}
    result = await create(client, user, reuse)
    assert first['id'] == result['id'] and 'reused' == result['upload_outcome']
    assert '保留原名称' == result['title'] and '2026-09-20' == result['examination_date']
    assert '原备注' == result['notes'] and 'lab' == result['category'] and 0 == result['revision']
    assert first['updated_at'] == result['updated_at']
    assert before_review == (await client.get(url+'/review', headers=auth)).json()
    assert before_links == await link_state(client, url, auth)
    assert result == await create(client, user, reuse)
    changed = reuse | {'duplicate_mode': 'separate', 'duplicate_report_id': None}
    assert 409 == (await client.post(BASE, headers=headers(user), **multipart(changed))).status_code
    separate = metadata(title='明确另存', duplicate_mode='separate')
    second = await create(client, user, separate)
    assert first['id'] != second['id'] and 'archived' == second['upload_outcome']
    assert second == await create(client, user, separate)
    assert 2 == (await client.get(BASE, headers=headers(user))).json()['total']
    assert 3 == await db_session.scalar(select(func.count()).select_from(ReportUploadSubmission).where(ReportUploadSubmission.patient_id == user.id))


@pytest.mark.asyncio
async def test_duplicates_only_match_own_ordered_bytes_and_validate_choice(client, db_session):
    owner, other = await patient(db_session), await patient(db_session)
    image, pdf = sample_image(), text_pdf()
    files = [('a.png', image, 'image/png'), ('b.pdf', pdf, 'application/pdf')]
    original = await create(client, owner, files=files)
    # 他人相同字节正常归档，不泄漏另一患者存在相同报告。
    other_report = await create(client, other, files=files)
    bad = metadata(duplicate_mode='reuse', duplicate_report_id=other_report['id'])
    assert 404 == (await client.post(BASE, headers=headers(owner), **multipart(bad, files))).status_code
    for changes in [{'duplicate_mode': 'reuse'}, {'duplicate_report_id': original['id']},
                    {'duplicate_mode': 'separate', 'duplicate_report_id': original['id']}, {'duplicate_mode': 'unknown'}]:
        assert 422 == (await client.post(BASE, headers=headers(owner), **multipart(metadata(**changes), files))).status_code
    different = metadata(duplicate_mode='reuse', duplicate_report_id=original['id'])
    assert 409 == (await client.post(BASE, headers=headers(owner), **multipart(different, list(reversed(files))))).status_code
    reversed_report = await create(client, owner, files=list(reversed(files)))
    assert original['id'] != reversed_report['id']
    renamed = [('不同名.png', image, 'image/png'), ('不同名.pdf', pdf, 'application/pdf')]
    duplicate = await client.post(BASE, headers=headers(owner), **multipart(metadata(), renamed))
    assert 409 == duplicate.status_code
    assert [original['id']] == [item['id'] for item in duplicate.json()['detail']['reports']]
    for index in range(6):
        await create(client, owner, metadata(title=f'本人明确另存{index}', duplicate_mode='separate'), files)
    result = (await client.post(BASE, headers=headers(owner), **multipart(metadata(), files))).json()['detail']
    assert 5 == len(result['reports']) and result['more'] is True
    assert other_report['id'] not in [item['id'] for item in result['reports']]


@pytest.mark.asyncio
async def test_legacy_receipt_fallback_and_deleted_result_never_recreates(client, db_session):
    user = await patient(db_session)
    data = metadata()
    first = await create(client, user, data)
    # 模拟旧部署行仍有原创建指纹；升级默认ask不能改变该合同。
    await db_session.execute(delete(ReportUploadSubmission).where(ReportUploadSubmission.patient_id == user.id))
    await db_session.commit()
    assert first == await create(client, user, data)
    reuse = metadata(duplicate_mode='reuse', duplicate_report_id=first['id'])
    await create(client, user, reuse)
    await db_session.execute(delete(PatientReport).where(PatientReport.id == UUID(first['id'])))
    await db_session.commit()
    receipt = await db_session.get(ReportUploadSubmission, (user.id, UUID(reuse['request_id'])))
    assert receipt is not None and receipt.report_id is None
    assert 410 == (await client.post(BASE, headers=headers(user), **multipart(reuse))).status_code
    assert 0 == (await client.get(BASE, headers=headers(user))).json()['total']
    new_data = metadata(title='验证创建编号墓碑')
    new_report = await create(client, user, new_data)
    await db_session.execute(delete(PatientReport).where(PatientReport.id == UUID(new_report['id'])))
    await db_session.commit()
    assert 410 == (await client.post(BASE, headers=headers(user), **multipart(new_data))).status_code
    assert 0 == (await client.get(BASE, headers=headers(user))).json()['total']


@pytest.mark.asyncio
async def test_concurrent_different_submissions_prompt_and_reuse_once(test_engine, db_session):
    user = await patient(db_session)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async def fresh_db():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = fresh_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as api:
            responses = await asyncio.gather(*[api.post(BASE, headers=headers(user), **multipart(metadata())) for _ in range(2)])
            assert [201, 409] == sorted(response.status_code for response in responses)
            first = next(response.json() for response in responses if response.status_code == 201)
            data = metadata(duplicate_mode='reuse', duplicate_report_id=first['id'])
            responses = await asyncio.gather(*[api.post(BASE, headers=headers(user), **multipart(data)) for _ in range(2)])
            assert [201, 201] == [response.status_code for response in responses]
            assert responses[0].json() == responses[1].json()
            assert 1 == (await api.get(BASE, headers=headers(user))).json()['total']
    finally:
        app.dependency_overrides.clear()
