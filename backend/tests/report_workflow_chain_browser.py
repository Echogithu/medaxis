"""报告T3真实页面验收；认证使用合成JWT，模型回答为本机固定合成响应。"""
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

LINE = 'WBC 6.2 10^9/L 3.5-9.5 ↑'


def main():
    api, web, model = [os.environ[key] for key in ['REPORTS_API_URL', 'REPORTS_WEB_URL', 'REPORTS_MODEL_URL']]
    assert all(urlsplit(url).hostname in {'127.0.0.1', 'localhost'} for url in [api, web, model])
    database = urlsplit(os.environ['DATABASE_URL'])
    assert database.hostname in {'127.0.0.1', 'localhost'} and database.path.startswith('/medaxis_demo_e2e_')
    artifact = Path(os.environ['REPORTS_WORKFLOW_ARTIFACT'])
    token = os.environ['REPORTS_BROWSER_TOKEN']
    auth = {'Authorization': f'Bearer {token}'}
    control = {'X-Test-Control': os.environ['REPORTS_CONTROL_TOKEN']}
    errors, checks = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(20000)

        def login(target):
            target.goto(web)
            target.evaluate("token => {localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)

        def wire(): return context.request.get(model+'/test/wire', headers=control).json()

        def worker(action):
            response = context.request.post(model+'/test/worker/'+action, headers=control, timeout=30000)
            assert response.status == 200

        def workspace():
            response = context.request.get(api+base+'/workspace', headers=auth)
            assert response.status == 200
            return response.json()

        def wait_job(kind, status):
            for _ in range(150):
                value = workspace()[kind+'_job']
                if value and value['status'] == status: return value
                if value and value['status'] == 'failed' and status != 'failed':
                    raise AssertionError(f"{kind}: {value['error_code']}")
                page.wait_for_timeout(500)
            raise AssertionError(f'{kind} never became {status}')

        def prepare(text):
            page.get_by_label('第 1 页文字', exact=True).fill(text)
            page.get_by_role('button', name='生成脱敏预览', exact=True).click()
            dialog = page.get_by_role('dialog', name='确认本次 AI 整理', exact=True)
            expect(dialog).to_be_visible()
            return dialog

        def approve(dialog):
            dialog.get_by_role('checkbox', name='我确认本次文字来自本人的报告', exact=True).check()
            dialog.get_by_role('checkbox', name='我已检查上方脱敏文字，同意本次发送给显示的接收模型', exact=True).check()

        try:
            login(page)
            payload = {'title': '合成报告工作区验收', 'category': 'lab', 'institution': '',
                'examination_date': None, 'report_date': None, 'notes': '', 'ownership_declared': True, 'request_id': str(uuid4())}
            files = [{'name': name, 'type': mime, 'data': base64.b64encode((artifact/name).read_bytes()).decode()}
                for name, mime in [('synthetic-two-pages.pdf', 'application/pdf'), ('synthetic-image.png', 'image/png')]]
            report = page.evaluate("""async ({metadata, files}) => {
                const body = new FormData(); body.append('metadata', JSON.stringify(metadata));
                for (const item of files) body.append('files', new File([Uint8Array.from(atob(item.data), c=>c.charCodeAt(0))], item.name, {type:item.type}));
                const response = await fetch('/api/v1/patient/reports', {method:'POST',headers:{Authorization:'Bearer '+localStorage.getItem('access_token')},body});
                if (!response.ok) throw new Error('Synthetic archive status '+response.status);
                return response.json();
            }""", {'metadata': payload, 'files': files})
            assert report['page_count'] == 3
            base = f'/api/v1/patient/reports/{report["id"]}'
            page.goto(f'{web}/reports/{report["id"]}')
            expect(page.get_by_label('第 1 页文字', exact=True)).to_be_visible()
            page.get_by_role('button', name='本地识别文字', exact=True).click()
            expect(page.get_by_text('本地识别：等待处理', exact=True)).to_be_visible()
            job_id = workspace()['extract_job']['id']
            page.reload()
            expect(page.get_by_text('本地识别：等待处理', exact=True)).to_be_visible()
            assert job_id == workspace()['extract_job']['id'] and wire() == []
            worker('start')
            extracted = wait_job('extract', 'completed')
            assert [1, 2, 3] == [item['page'] for item in extracted['result']['pages']]
            assert [1, 2, 1] == [item['file_page'] for item in extracted['result']['pages']]
            assert 'WBC' in extracted['result']['pages'][0]['text'] and '6.2' in extracted['result']['pages'][2]['text']
            expect(page.get_by_text('本地识别：已完成', exact=True)).to_be_visible()
            checks.append('真实队列保存与刷新恢复；worker启动后完成PDF2页+图片本地取字，原始页序正确，无模型请求')
            page.get_by_label('第 1 页文字', exact=True).fill('本页未保存文字')
            page.get_by_role('button', name='刷新进度', exact=True).click()
            expect(page.get_by_label('第 1 页文字', exact=True)).to_have_value('本页未保存文字')
            dialog = prepare('合成患者本人 13800000000\n报告号：SYNTHETIC001\n'+LINE+'\nhttps://example.invalid/private-original')
            preview = workspace()['preview']
            expect(dialog.get_by_label('本次将发送的完整文字', exact=True)).to_have_value(preview['text'])
            for hidden in ['合成患者本人', '13800000000', 'SYNTHETIC001', 'https://example.invalid/private-original']:
                assert hidden not in preview['text']
            expect(dialog.get_by_text('接收方：synthetic-report · synthetic-report-model · '+model, exact=True)).to_be_visible()
            send = dialog.get_by_role('button', name='同意并整理', exact=True)
            expect(send).to_be_disabled()
            approve(dialog); expect(send).to_be_enabled()
            dialog.get_by_role('button', name='暂不发送', exact=True).click()
            page.get_by_role('button', name='查看已保存预览', exact=True).click()
            expect(send).to_be_disabled()
            assert not any(dialog.get_by_role('checkbox').nth(i).is_checked() for i in range(2))
            approve(dialog)
            # 第二窗口改预览；显式调用真实刷新按钮的DOM事件，模拟弹窗打开时收到新工作区。
            # 无响应伪造；模态遮罩正常阻止指针点击，因此这里用事件注入覆盖异步更新反例。
            view = workspace()
            newer = context.request.post(api+base+'/preview', headers=auth, data={
                'expected_source_version': view['source_version'], 'expected_workflow_revision': view['revision'],
                'pages': [{'page': 1, 'text': LINE+'\n第二窗口修改'}, {'page': 2, 'text': ''}, {'page': 3, 'text': ''}]})
            assert newer.status == 200
            page.evaluate("[...document.querySelectorAll('button')].find(button=>button.textContent==='刷新进度').click()")
            expect(dialog.get_by_label('本次将发送的完整文字', exact=True)).to_have_value(newer.json()['preview']['text'])
            expect(send).to_be_disabled()
            assert not any(dialog.get_by_role('checkbox').nth(i).is_checked() for i in range(2))
            approve(dialog)
            submitted = workspace()['preview']
            # 实际202已到浏览器，随后丢弃第一次成功响应，验证同UUID重试。
            page.evaluate("""(() => {const original=window.fetch.bind(window);let lose=true;
                window.fetch=async(input,init)=>{const response=await original(input,init);
                    if(lose&&String(input).endsWith('/ai')&&init?.method==='POST'&&response.ok){lose=false;throw new TypeError('Synthetic response lost');}
                    return response;};})();""")
            send.click()
            retry = dialog.get_by_role('button', name='使用原编号重试提交', exact=True)
            expect(retry).to_be_enabled()
            original_job = workspace()['ai_job']
            retry.click()
            expect(dialog).not_to_be_visible()
            completed = wait_job('ai', 'completed')
            assert original_job['id'] == completed['id'] and original_job['request_id'] == completed['request_id']
            assert len(wire()) == 1
            outbound = wire()[0]
            assert outbound['messages'][1]['content'] == submitted['text']
            assert all(isinstance(message['content'], str) for message in outbound['messages'])
            for hidden in [report['id'], *[item['id'] for item in report['files']], *[item['filename'] for item in report['files']], 'image_url', 'data:image']:
                assert hidden not in json.dumps(outbound, ensure_ascii=False)
            expect(page.get_by_text('AI 整理结果 · 待本人核对', exact=True)).to_be_visible()
            expect(page.get_by_text('WBC：6.2', exact=True)).to_be_visible()
            assert completed['result']['review_status'] == 'unverified'
            checks.append('完整脱敏文字/实际接收方；默认未勾选、关闭清除、跨窗口预览变化立即失效；响应丢失重试同UUID且真实HTTP仅1次')
            page.get_by_text('AI 整理结果 · 待本人核对', exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(artifact/'desktop-candidate.png'), full_page=True, animations='disabled')
            dialog = prepare(LINE+'\nCANCEL_TEST')
            approve(dialog); dialog.get_by_role('button', name='同意并整理', exact=True).click()
            for _ in range(100):
                if len(wire()) == 2: break
                page.wait_for_timeout(100)
            assert len(wire()) == 2
            page.get_by_role('button', name='取消整理', exact=True).click()
            expect(page.get_by_text('已停止发布本次结果；已经或可能发送的文字无法召回', exact=True)).to_be_visible()
            page.wait_for_timeout(4000)
            cancelled = workspace()['ai_job']
            assert cancelled['status'] == 'cancelled' and cancelled['result'] is None
            page.reload()
            expect(page.get_by_text('AI 整理：已取消', exact=True)).to_be_visible()
            expect(page.get_by_text('AI 整理结果 · 待本人核对', exact=True)).not_to_be_visible()
            worker('stop')
            dialog = prepare(LINE+'\nQUEUED_CANCEL')
            approve(dialog); dialog.get_by_role('button', name='同意并整理', exact=True).click()
            expect(page.get_by_text('AI 整理：等待处理', exact=True)).to_be_visible()
            page.get_by_role('button', name='取消整理', exact=True).click()
            expect(page.get_by_text('任务已停止，不会发送本次待处理文字', exact=True)).to_be_visible()
            worker('start'); page.wait_for_timeout(4000)
            assert len(wire()) == 2 and workspace()['ai_job']['status'] == 'cancelled'
            checks.append('发送后取消提示无法召回，晚到结果不发布；worker停机期间取消queued任务，重启不外发')
            other_auth = {'Authorization': 'Bearer '+os.environ['REPORTS_OTHER_TOKEN']}
            assert 404 == context.request.get(api+base+'/workspace', headers=other_auth).status
            assert 404 == context.request.post(api+base+'/jobs/'+cancelled['id']+'/cancel', headers=other_auth).status
            assert [] == context.request.get(api+'/api/v1/patient/care-plans', headers=auth).json()
            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True)
            phone = mobile.new_page(); phone.on('pageerror', lambda error: errors.append(str(error)))
            login(phone); phone.goto(f'{web}/reports/{report["id"]}')
            phone.get_by_role('tab', name='整理报告', exact=True).click()
            expect(phone.get_by_text('AI 整理：已取消', exact=True)).to_be_visible()
            phone.get_by_label('第 1 页文字', exact=True).fill(LINE+'\n手机填写')
            phone.get_by_role('tab', name='查看原件', exact=True).click()
            expect(phone.get_by_title('PDF报告原件')).to_be_visible()
            phone.get_by_role('tab', name='整理报告', exact=True).click()
            expect(phone.get_by_label('第 1 页文字', exact=True)).to_have_value(LINE+'\n手机填写')
            phone.get_by_role('button', name='生成脱敏预览', exact=True).click()
            modal = phone.get_by_role('dialog', name='确认本次 AI 整理', exact=True)
            expect(modal).to_be_visible()
            expect(modal.get_by_role('button', name='同意并整理', exact=True)).to_be_disabled()
            assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            phone.screenshot(path=str(artifact/'mobile-consent.png'), full_page=True, animations='disabled')
            modal.get_by_role('checkbox', name='我确认本次文字来自本人的报告', exact=True).check()
            expect(modal.get_by_role('button', name='同意并整理', exact=True)).to_be_disabled()
            modal.get_by_role('checkbox', name='我已检查上方脱敏文字，同意本次发送给显示的接收模型', exact=True).check()
            expect(modal.get_by_role('button', name='同意并整理', exact=True)).to_be_enabled()
            modal.get_by_role('button', name='暂不发送', exact=True).click()
            assert len(wire()) == 2
            phone.reload(); phone.get_by_role('tab', name='整理报告', exact=True).click()
            expect(phone.get_by_label('第 1 页文字', exact=True)).to_have_value(workspace()['preview']['pages'][0]['text'])
            mobile.close()
            checks.append('双账号工作区/取消404；新手机上下文恢复进度、原件/整理切换保留填写、预览可操作无横向溢出，已保存文字刷新恢复')
            assert not errors, errors
            result = {'report_id': report['id'], 'passed': checks, 'page_errors': errors,
                'model_quality': 'synthetic only', 'cross_window_update': 'real API + injected refresh DOM event'}
            (artifact/'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception:
            page.screenshot(path=str(artifact/'failure.png'), full_page=True, animations='disabled')
            (artifact/'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
            raise
        finally: browser.close()


if __name__ == '__main__': main()
