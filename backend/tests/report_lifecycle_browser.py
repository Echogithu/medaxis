"""真实Edge回收站/恢复/永久删除及响应丢失、并发状态确认。"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from playwright.sync_api import expect, sync_playwright


def main():
    api, web = os.environ['REPORTS_API_URL'], os.environ['REPORTS_WEB_URL']
    assert all(urlsplit(url).hostname in {'127.0.0.1', 'localhost'} for url in [api, web])
    assert urlsplit(os.environ['DATABASE_URL']).path.startswith('/medaxis_demo_e2e_')
    artifact = Path(os.environ['REPORTS_REVIEW_ARTIFACT']); token = os.environ['REPORTS_BROWSER_TOKEN']
    auth = {'Authorization': 'Bearer '+token}; checks, errors, paths = [], [], []
    original_bytes = (artifact/'synthetic-report.png').read_bytes()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page(); active_page = page; page.set_default_timeout(20000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        context.on('request', lambda req: paths.append(urlsplit(req.url).path))
        def login(target):
            target.goto(web)
            target.evaluate("token=>{localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)
        def seed(title, separate=False):
            data = {'request_id': str(uuid4()), 'title': title, 'category': 'lab', 'ownership_declared': True}
            if separate: data['duplicate_mode'] = 'separate'
            response = context.request.post(api+'/api/v1/patient/reports', headers=auth, multipart={
                'metadata': json.dumps(data), 'files': {'name': 'synthetic-report.png', 'mimeType': 'image/png', 'buffer': original_bytes}})
            assert response.status == 201
            return response.json(), data
        def state(report):
            response = context.request.get(api+'/api/v1/patient/reports/'+report['id']+'/lifecycle', headers=auth)
            assert response.status == 200; return response.json()
        def inject_loss(target, action):
            target.evaluate("""action=>{const original=window.fetch.bind(window);let lose=true;window.managementCalls=[];
              window.fetch=async(input,init)=>{if(String(input).endsWith('/lifecycle/'+action)&&init?.method==='POST'){
                window.managementCalls.push(JSON.parse(init.body));const response=await original(input,init);
                if(lose&&response.ok){lose=false;throw new TypeError('Synthetic management response lost');}return response;}return original(input,init);};}""", action)
        def checkbox(dialog, action):
            names = {'trash': '我已了解影响，确认移入回收站', 'restore': '我确认恢复报告', 'purge': '我确认彻底删除此报告及其原件、文字和核对历史'}
            return dialog.get_by_role('checkbox', name=names[action], exact=True)
        try:
            report, original_data = seed('桌面生命周期合成报告')
            mobile_report, _ = seed('手机生命周期合成报告', separate=True)
            base = '/api/v1/patient/reports/'+report['id']
            case = context.request.post(api+'/api/v1/medical-cases', headers=auth, data={'title': '合成生命周期病例'}).json()
            links = context.request.get(api+base+'/case-links', headers=auth).json()
            response = context.request.post(api+base+'/case-links', headers=auth, data={'request_id': str(uuid4()),
                'expected_links_revision': links['links_revision'], 'expected_review_revision': links['review_revision'],
                'expected_source_hash': links['source_hash'], 'case_ids': [case['id']], 'refresh_case_ids': []})
            assert response.status == 200
            login(page); page.goto(web+'/reports/'+report['id'])
            page.get_by_role('button', name='移入回收站', exact=True).click()
            modal = page.get_by_role('dialog', name='移入回收站', exact=True)
            expect(modal.get_by_text('桌面生命周期合成报告', exact=True)).to_be_visible()
            expect(modal.get_by_text('将解除 1 个病例关联', exact=False)).to_be_visible()
            expect(modal.get_by_role('button', name='确认移入回收站', exact=True)).to_be_disabled()
            modal.get_by_role('button', name='暂不操作', exact=True).click()
            assert state(report)['report']['archive_status'] == 'archived'
            page.get_by_role('button', name='移入回收站', exact=True).click()
            checkbox(modal, 'trash').check(); inject_loss(page, 'trash')
            modal.get_by_role('button', name='确认移入回收站', exact=True).click()
            expect(modal.get_by_role('button', name='使用原编号重试操作', exact=True)).to_be_enabled()
            expect(checkbox(modal, 'trash')).to_be_disabled()
            assert state(report)['report']['archive_status'] == 'trash' and state(report)['links_count'] == 0
            modal.get_by_role('button', name='暂收起（保留原提交）', exact=True).click()
            page.get_by_role('button', name='继续确认操作结果', exact=True).click()
            modal.get_by_role('button', name='使用原编号重试操作', exact=True).click()
            expect(page.get_by_role('heading', name='检查报告回收站', exact=True)).to_be_visible()
            calls = page.evaluate('window.managementCalls'); assert len(calls) == 2 and calls[0] == calls[1]
            assert context.request.get(api+'/api/v1/patient/cases/'+case['id']+'/reports', headers=auth).json()['total'] == 0
            checks.append('移除前本人报告/引用影响和确认可见；取消无副作用；成功丢响应收起恢复原编号重试，仅一次移除且撤引用')

            card = page.locator('article').filter(has_text='桌面生命周期合成报告')
            card.get_by_role('button', name='恢复报告', exact=True).click()
            restore = page.get_by_role('dialog', name='恢复报告', exact=True)
            expect(restore.get_by_text('不会恢复病例关联', exact=False)).to_be_visible()
            expect(restore.get_by_role('button', name='确认恢复报告', exact=True)).to_be_disabled()
            checkbox(restore, 'restore').check(); restore.get_by_role('button', name='确认恢复报告', exact=True).click()
            expect(card).not_to_be_visible()
            page.get_by_role('button', name='返回已归档报告', exact=True).click()
            card = page.locator('article').filter(has_text='桌面生命周期合成报告')
            expect(card).to_be_visible()
            assert context.request.get(api+base+'/files/'+report['files'][0]['id'], headers=auth).body() == original_bytes
            workspace = context.request.get(api+base+'/workspace', headers=auth).json()
            assert workspace['preview'] is None and workspace['ai_job'] is None and workspace['extract_job'] is None
            checks.append('回收站恢复需确认；原件字节保留，未恢复病例/整理任务/同意，返回活动列表可查')

            card.get_by_role('button', name='移入回收站', exact=True).click()
            expect(modal.get_by_text('桌面生命周期合成报告', exact=True)).to_be_visible()
            fields = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
            response = context.request.patch(api+base, headers=auth, data=fields | {'title': '另一个窗口更新的合成报告', 'expected_revision': 0})
            assert response.status == 200
            checkbox(modal, 'trash').check(); modal.get_by_role('button', name='确认移入回收站', exact=True).click()
            expect(modal.get_by_role('alert')).to_contain_text('尚未执行本次操作')
            assert state(report)['report']['archive_status'] == 'archived'
            modal.get_by_role('button', name='查看最新影响，重新确认', exact=True).click()
            expect(modal.get_by_text('另一个窗口更新的合成报告', exact=True)).to_be_visible()
            expect(checkbox(modal, 'trash')).not_to_be_checked()
            checkbox(modal, 'trash').check(); modal.get_by_role('button', name='确认移入回收站', exact=True).click()
            expect(modal).not_to_be_visible()
            page.get_by_role('button', name='回收站（1）', exact=True).click()
            expect(page.get_by_role('heading', name='检查报告回收站', exact=True)).to_be_visible()
            page.screenshot(path=str(artifact/'desktop-trash.png'), full_page=True, animations='disabled')
            checks.append('真实第二窗口修改使旧管理token409；确认清除，重新载入最新影响再显式确认才移除')

            card = page.locator('article').filter(has_text='另一个窗口更新的合成报告')
            card.get_by_role('button', name='彻底删除', exact=True).click()
            purge = page.get_by_role('dialog', name='彻底删除', exact=True)
            expect(purge.get_by_text('无法从回收站恢复', exact=False)).to_be_visible()
            expect(purge.get_by_role('button', name='确认彻底删除', exact=True)).to_be_disabled()
            purge.get_by_role('button', name='暂不操作', exact=True).click()
            assert state(report)['report']['archive_status'] == 'trash'
            card.get_by_role('button', name='彻底删除', exact=True).click()
            checkbox(purge, 'purge').check(); inject_loss(page, 'purge')
            purge.get_by_role('button', name='确认彻底删除', exact=True).click()
            expect(purge.get_by_role('button', name='使用原编号重试操作', exact=True)).to_be_enabled()
            assert context.request.get(api+base+'/lifecycle', headers=auth).status == 404
            purge.get_by_role('button', name='使用原编号重试操作', exact=True).click()
            expect(page.get_by_text('回收站为空', exact=True)).to_be_visible()
            calls = page.evaluate('window.managementCalls'); assert len(calls) == 2 and calls[0] == calls[1]
            assert context.request.get(api+base+'/files/'+report['files'][0]['id'], headers=auth).status == 404
            replay = context.request.post(api+'/api/v1/patient/reports', headers=auth, multipart={
                'metadata': json.dumps(original_data), 'files': {'name': 'synthetic-report.png', 'mimeType': 'image/png', 'buffer': original_bytes}})
            assert replay.status == 410
            checks.append('彻底删除单独确认，取消不删；成功丢响应同UUID重试可完成；原件404、旧创建提交410不复活')

            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True)
            phone = mobile.new_page(); active_page = phone; phone.set_default_timeout(20000)
            phone.on('pageerror', lambda error: errors.append(str(error)))
            mobile.on('request', lambda req: paths.append(urlsplit(req.url).path))
            login(phone); phone.goto(web+'/reports')
            mobile_card = phone.locator('article').filter(has_text='手机生命周期合成报告')
            mobile_card.get_by_role('button', name='移入回收站', exact=True).click()
            mobile_modal = phone.get_by_role('dialog', name='移入回收站', exact=True)
            expect(mobile_modal.get_by_text('手机生命周期合成报告', exact=True)).to_be_visible()
            assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert mobile_modal.evaluate('element=>element.scrollWidth <= element.clientWidth')
            checkbox(mobile_modal, 'trash').check(); mobile_modal.get_by_role('button', name='确认移入回收站', exact=True).click()
            expect(mobile_modal).not_to_be_visible()
            phone.get_by_role('button', name='回收站（1）', exact=True).click()
            mobile_card.get_by_role('button', name='恢复报告', exact=True).click()
            mobile_restore = phone.get_by_role('dialog', name='恢复报告', exact=True)
            checkbox(mobile_restore, 'restore').check(); mobile_restore.get_by_role('button', name='确认恢复报告', exact=True).click()
            expect(phone.get_by_text('回收站为空', exact=True)).to_be_visible()
            phone.get_by_role('button', name='返回已归档报告', exact=True).click()
            mobile_card.get_by_role('button', name='移入回收站', exact=True).click()
            checkbox(mobile_modal, 'trash').check(); mobile_modal.get_by_role('button', name='确认移入回收站', exact=True).click()
            expect(mobile_modal).not_to_be_visible(); phone.get_by_role('button', name='回收站（1）', exact=True).click()
            mobile_card.get_by_role('button', name='彻底删除', exact=True).click()
            mobile_purge = phone.get_by_role('dialog', name='彻底删除', exact=True)
            expect(mobile_purge.get_by_text('无法从回收站恢复', exact=False)).to_be_visible()
            phone.screenshot(path=str(artifact/'mobile-purge.png'), animations='disabled')
            checkbox(mobile_purge, 'purge').check(); mobile_purge.get_by_role('button', name='确认彻底删除', exact=True).click()
            expect(phone.get_by_text('回收站为空', exact=True)).to_be_visible()
            assert context.request.get(api+'/api/v1/patient/reports/'+mobile_report['id'], headers=auth).status == 404
            mobile.close(); active_page = page
            checks.append('390px新上下文可移除/恢复/单独确认彻底删除；无横向溢出，服务端结果持久化')
            assert not any('/documents' in path or path.endswith('/ai') or path.endswith('/extract') for path in paths)
            assert not errors, errors
            result = {'passed': checks, 'page_errors': errors}
            (artifact/'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception:
            active_page.screenshot(path=str(artifact/'lifecycle-failure.png'), full_page=True)
            (artifact/'lifecycle-failure-aria.txt').write_text(active_page.locator('body').aria_snapshot(), encoding='utf-8')
            raise
        finally:
            context.close(); browser.close()


if __name__ == '__main__': main()
