"""真实Edge上传去重选择、响应丢失重试、批次恢复和手机操作。"""
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
    artifact = Path(os.environ['REPORTS_REVIEW_ARTIFACT'])
    token = os.environ['REPORTS_BROWSER_TOKEN']; auth = {'Authorization': 'Bearer '+token}
    checks, errors, paths = [], [], []
    image = artifact/'synthetic-report.png'
    broken = artifact/'synthetic-broken.png'; broken.write_bytes(b'not-a-real-image')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page(); page.set_default_timeout(20000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        context.on('request', lambda request: paths.append(urlsplit(request.url).path))
        def login(target):
            target.goto(web)
            target.evaluate("token=>{localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)
            target.goto(web+'/reports')
        def listing():
            response = context.request.get(api+'/api/v1/patient/reports', headers=auth)
            assert response.status == 200
            return response.json()
        def open_upload(target, name):
            target.get_by_role('button', name='上传检查报告', exact=True).click()
            dialog = target.get_by_role('dialog', name='上传检查报告', exact=True)
            dialog.get_by_label('选择报告文件').set_input_files(str(image))
            group = dialog.get_by_role('region', name='第1份报告', exact=True)
            group.get_by_label('报告名称', exact=False).fill(name)
            group.get_by_role('checkbox', name='我确认归档的是本人报告', exact=True).check()
            dialog.get_by_role('button', name='保存原件', exact=True).click()
            return dialog, group
        try:
            # 真实API种一份原件，UI另存/复用也通过真实后端，不拦截业务响应。
            response = context.request.post(api+'/api/v1/patient/reports', headers=auth, multipart={
                'metadata': json.dumps({'request_id': str(uuid4()), 'title': '原报告保留', 'category': 'lab', 'ownership_declared': True}),
                'files': {'name': image.name, 'mimeType': 'image/png', 'buffer': image.read_bytes()}})
            assert response.status == 201
            original = response.json()
            login(page)
            dialog, group = open_upload(page, '本页名称不能覆盖')
            choices = group.get_by_role('region', name='重复报告选择', exact=True)
            expect(choices).to_be_visible()
            expect(choices.get_by_text('原报告保留', exact=True)).to_be_visible()
            expect(group.get_by_label('报告名称', exact=False)).to_have_value('本页名称不能覆盖')
            assert listing()['total'] == 1
            choices.scroll_into_view_if_needed()
            page.screenshot(path=str(artifact/'desktop-duplicate.png'), animations='disabled')
            # 后端已复用提交，但抛弃成功响应；记录选择/UUID便于证明冻结重试。
            page.evaluate("""(()=>{const original=window.fetch.bind(window);let lose=true;window.dedupCalls=[];
                window.fetch=async(input,init)=>{if(String(input).endsWith('/patient/reports')&&init?.method==='POST'){
                  const metadata=JSON.parse(init.body.get('metadata'));window.dedupCalls.push(metadata);
                  const response=await original(input,init);if(lose&&metadata.duplicate_mode==='reuse'&&response.ok){lose=false;throw new TypeError('Synthetic reuse response lost');}return response;}return original(input,init);};})();""")
            choices.get_by_role('button', name='复用这份报告', exact=True).click()
            expect(group.get_by_role('alert')).to_contain_text('结果暂未确认')
            expect(group.get_by_label('报告名称', exact=False)).to_be_disabled()
            dialog.get_by_role('button', name='暂收起（保留待处理项）', exact=True).click()
            page.get_by_role('button', name='继续处理', exact=True).click()
            dialog.get_by_role('button', name='重试未完成项', exact=True).click()
            expect(group.get_by_text('已复用', exact=True)).to_be_visible()
            expect(dialog.get_by_role('status')).to_contain_text('新增 0，复用 1')
            calls = page.evaluate('window.dedupCalls'); assert len(calls) == 2 and calls[0] == calls[1]
            assert calls[0]['duplicate_report_id'] == original['id']
            assert listing()['total'] == 1 and listing()['items'][0]['title'] == '原报告保留'
            dialog.get_by_role('button', name='完成', exact=True).click()
            checks.append('本人重复候选及原填写可见；复用丢响应/收起恢复后同编号同选择重试，不覆盖原报告或增加统计')

            dialog, group = open_upload(page, '明确另存的报告')
            choices = group.get_by_role('region', name='重复报告选择', exact=True)
            expect(choices).to_be_visible()
            choices.get_by_role('button', name='仍然另存一份', exact=True).click()
            expect(group.get_by_text('已归档', exact=True)).to_be_visible()
            assert listing()['total'] == 2
            assert {'原报告保留', '明确另存的报告'} == {item['title'] for item in listing()['items']}
            dialog.get_by_role('button', name='完成', exact=True).click(); page.reload()
            expect(page.get_by_text('明确另存的报告', exact=True)).to_be_visible()
            checks.append('明确另存新增独立报告；刷新后原份与新份同时保留')

            dialog, group = open_upload(page, '批次重复项')
            choices = group.get_by_role('region', name='重复报告选择', exact=True)
            expect(choices).to_be_visible()
            dialog.get_by_role('button', name='选择其他报告', exact=True).click()
            dialog.get_by_label('选择报告文件').set_input_files(str(broken))
            second = dialog.get_by_role('region', name='第2份报告', exact=True)
            second.get_by_role('checkbox').check()
            dialog.get_by_role('button', name='保存原件', exact=True).click()
            expect(second.get_by_role('alert')).to_be_visible()
            expect(choices).to_be_visible()
            choices.get_by_role('button', name='复用这份报告', exact=True).first.click()
            expect(group.get_by_text('已复用', exact=True)).to_be_visible()
            assert listing()['total'] == 2
            second.get_by_role('button', name='取消此份', exact=True).click()
            dialog.get_by_role('button', name='完成', exact=True).click()
            checks.append('重复项保留选择，另一批次损坏原件显式失败；复用成功独立保留，取消失败项不影响已有资料')

            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True)
            phone = mobile.new_page(); phone.set_default_timeout(20000)
            phone.on('pageerror', lambda error: errors.append(str(error)))
            mobile.on('request', lambda request: paths.append(urlsplit(request.url).path))
            login(phone)
            modal, one = open_upload(phone, '手机复用不另存')
            options = one.get_by_role('region', name='重复报告选择', exact=True)
            expect(options).to_be_visible()
            options.scroll_into_view_if_needed()
            assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert modal.evaluate('element => element.scrollWidth <= element.clientWidth')
            phone.screenshot(path=str(artifact/'mobile-duplicate.png'), animations='disabled')
            options.get_by_role('button', name='复用这份报告', exact=True).first.click()
            expect(one.get_by_text('已复用', exact=True)).to_be_visible()
            modal.get_by_role('button', name='完成', exact=True).click()
            assert listing()['total'] == 2
            mobile.close()
            checks.append('390px新上下文重复预览和复用均可操作，无横向溢出，不自动AI或新增报告')
            assert not any('/documents' in path or path.endswith('/extract') or path.endswith('/ai') for path in paths)
            assert not errors, errors
            result = {'passed': checks, 'page_errors': errors}
            (artifact/'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception:
            page.screenshot(path=str(artifact/'dedup-failure.png'), full_page=True)
            (artifact/'dedup-failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
            raise
        finally:
            context.close(); browser.close()


if __name__ == '__main__': main()
