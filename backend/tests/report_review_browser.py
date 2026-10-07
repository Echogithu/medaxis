"""真实Edge人工编辑/确认/历史；只用合成JWT、原件及预置合成AI候选。"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main():
    api, web = os.environ['REPORTS_API_URL'], os.environ['REPORTS_WEB_URL']
    assert all(urlsplit(url).hostname in {'127.0.0.1', 'localhost'} for url in [api, web])
    database = urlsplit(os.environ['DATABASE_URL'])
    assert database.hostname in {'127.0.0.1', 'localhost'} and database.path.startswith('/medaxis_demo_e2e_')
    artifact = Path(os.environ['REPORTS_REVIEW_ARTIFACT'])
    token = os.environ['REPORTS_BROWSER_TOKEN']; auth = {'Authorization': 'Bearer '+token}
    errors, checks, paths = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page(); page.set_default_timeout(20000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        context.on('request', lambda request: paths.append((urlsplit(request.url).path, request.method)))

        def login(target):
            target.goto(web)
            target.evaluate("token => {localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)

        def upload(title, category):
            response = context.request.post(api+'/api/v1/patient/reports', headers=auth, multipart={
                'metadata': json.dumps({'title': title, 'category': category, 'request_id': str(uuid4()), 'ownership_declared': True}),
                'files': {'name': 'synthetic-report.png', 'mimeType': 'image/png', 'buffer': (artifact/'synthetic-report.png').read_bytes()}})
            assert response.status == 201
            return response.json()

        def view():
            response = context.request.get(api+base+'/review', headers=auth)
            assert response.status == 200
            return response.json()

        def confirm(target, panel):
            panel.get_by_role('button', name='确认已对照原件', exact=True).click()
            modal = target.get_by_role('dialog', name='确认这个已保存的草稿', exact=True)
            expect(modal.get_by_role('button', name='记录本人确认', exact=True)).to_be_disabled()
            modal.get_by_role('checkbox', name='我已逐项对照原件，确认这个草稿的填写', exact=True).check()
            modal.get_by_role('button', name='记录本人确认', exact=True).click()
            expect(modal).not_to_be_visible()

        try:
            login(page)
            report = upload('合成人工核对报告', 'lab'); base = '/api/v1/patient/reports/'+report['id']
            page.goto(web+'/reports/'+report['id'])
            panel = page.get_by_role('region', name='人工核对报告', exact=True)
            expect(panel).to_be_visible()
            expect(page.get_by_role('img', name='报告原件', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='确认已对照原件', exact=True)).to_be_disabled()
            panel.get_by_role('button', name='添加检验指标', exact=True).click()
            panel.get_by_label('项目名称 1', exact=True).fill('合成定性项目')
            panel.get_by_label('原始结果 1', exact=True).fill('阳性')
            panel.get_by_role('button', name='添加检验指标', exact=True).click()
            panel.get_by_label('项目名称 2', exact=True).fill('尚未填写的项目')
            page.evaluate("""(() => {const original=window.fetch.bind(window);let lose=true;
              window.fetch=async(input,init)=>{const response=await original(input,init);
                if(lose&&String(input).endsWith('/review/drafts')&&init?.method==='POST'&&response.ok){lose=false;throw new TypeError('Synthetic draft response lost');}return response;};})();""")
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_role('button', name='使用原编号重试保存', exact=True)).to_be_enabled()
            first_id = view()['draft']['id']
            panel.get_by_role('button', name='使用原编号重试保存', exact=True).click()
            expect(panel.get_by_text('草稿版本 1 已保存，尚未确认核对。', exact=True)).to_be_visible()
            assert first_id == view()['draft']['id'] and view()['confirmed'] is None
            expect(panel.get_by_role('button', name='确认已对照原件', exact=True)).to_be_disabled()
            panel.get_by_role('button', name='移除指标 2', exact=True).click()
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 2 已保存，尚未确认核对。', exact=True)).to_be_visible()
            assert view()['draft']['content']['indicators'][0]['unit'] is None
            panel.get_by_role('button', name='确认已对照原件', exact=True).click()
            modal = page.get_by_role('dialog', name='确认这个已保存的草稿', exact=True)
            expect(modal.get_by_role('button', name='记录本人确认', exact=True)).to_be_disabled()
            modal.get_by_role('button', name='暂不确认', exact=True).click()
            assert view()['confirmed'] is None
            confirm(page, panel)
            assert view()['review_status'] == 'patient_confirmed'
            confirmed_id = view()['confirmed']['id']
            confirmed_revision = view()['confirmed']['revision']
            checks.append('无AI人工添加/修改/移除，未完成草稿可保存不可确认；响应丢失同编号只存1版本；确认需单独勾选且仅确认已保存正文')
            page.reload()
            expect(panel.get_by_text('本人已核对', exact=True)).to_be_visible()
            listing = context.request.get(api+'/api/v1/patient/reports?pending_only=true', headers=auth).json()
            assert report['id'] not in [item['id'] for item in listing['items']]
            panel.get_by_label('原始结果 1', exact=True).fill('弱阳性')
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 4 已保存，尚未确认核对。', exact=True)).to_be_visible()
            assert view()['confirmed']['id'] == confirmed_id and view()['confirmed']['content']['indicators'][0]['raw_value'] == '阳性'
            panel.get_by_role('button', name='查看核对历史', exact=True).click()
            panel.get_by_role('button', name=f'查看版本 {confirmed_revision}', exact=True).click()
            expect(panel.get_by_text(f'历史版本 {confirmed_revision} · 本人确认 · 原件版本 1', exact=True)).to_be_visible()
            state = view()
            other = context.request.post(api+base+'/review/drafts', headers=auth, data={
                'request_id': str(uuid4()), 'expected_revision': state['revision'], 'expected_source_epoch': state['source_epoch'],
                'expected_source_version': state['source_version'], 'expected_source_hash': state['source_hash'],
                'content': {'indicators': [{'name': '合成定性项目', 'raw_value': '另窗口填写'}], 'sections': []}})
            assert other.status == 201
            panel.get_by_label('原始结果 1', exact=True).fill('本页未保存填写')
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('核对内容或来源已在其他页面更新，本页填写仍保留，请对照最新版本 本页填写仍保留。', exact=True)).to_be_visible()
            expect(panel.get_by_label('原始结果 1', exact=True)).to_have_value('本页未保存填写')
            panel.get_by_role('button', name='刷新核对进度', exact=True).click()
            expect(panel.get_by_role('button', name='采用最新来源，保留本页填写', exact=True)).to_be_visible()
            expect(panel.get_by_label('原始结果 1', exact=True)).to_have_value('本页未保存填写')
            panel.get_by_role('button', name='采用最新来源，保留本页填写', exact=True).click()
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 6 已保存，尚未确认核对。', exact=True)).to_be_visible()
            checks.append('草稿不覆盖上一确认；服务端真实历史可查看；并发409保留填写，刷新不默默改其基线，显式采用最新来源后保存')
            workflow = context.request.get(api+base+'/workspace', headers=auth).json()
            response = context.request.post(api+base+'/preview', headers=auth, data={
                'expected_source_version': workflow['source_version'], 'expected_workflow_revision': workflow['revision'],
                'pages': [{'page': 1, 'text': '新的合成关键文字'}]})
            assert response.status == 200
            page.reload()
            expect(panel.get_by_text('来源变化，需重新核对', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='确认已对照原件', exact=True)).to_be_disabled()
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 7 已保存，尚未确认核对。', exact=True)).to_be_visible()
            confirm(page, panel)
            assert view()['confirmed']['revision'] == 8
            old = context.request.get(api+base+'/review/versions/'+confirmed_id, headers=auth).json()
            assert not old['source_current'] and old['content']['indicators'][0]['raw_value'] == '阳性'
            panel.get_by_text('最近本人核对版本 8', exact=False).scroll_into_view_if_needed()
            original = page.get_by_role('img', name='报告原件', exact=True)
            expect(original).to_be_visible()
            bounds = original.bounding_box()
            assert bounds and bounds['y'] >= 72 and bounds['y'] < 1000 and bounds['x'] < 800, bounds
            page.screenshot(path=str(artifact/'desktop-review.png'), full_page=True, animations='disabled')
            checks.append('关键文字变更撤下当前确认标记、旧确认历史不变；未改值也可按新来源重新保存并核对')
            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True)
            phone = mobile.new_page(); phone.on('pageerror', lambda error: errors.append(str(error)))
            login(phone); phone.goto(web+'/reports/'+report['id'])
            phone.get_by_role('tab', name='人工核对', exact=True).click()
            mpanel = phone.get_by_role('region', name='人工核对报告', exact=True)
            expect(mpanel.get_by_label('原始结果 1', exact=True)).to_have_value('本页未保存填写')
            mpanel.get_by_label('原始结果 1', exact=True).fill('手机端修正')
            phone.get_by_role('tab', name='查看原件', exact=True).click()
            expect(phone.get_by_role('img', name='报告原件', exact=True)).to_be_visible()
            phone.get_by_role('tab', name='人工核对', exact=True).click()
            expect(mpanel.get_by_label('原始结果 1', exact=True)).to_have_value('手机端修正')
            mpanel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(mpanel.get_by_text('草稿版本 9 已保存，尚未确认核对。', exact=True)).to_be_visible()
            confirm(phone, mpanel)
            assert view()['confirmed']['revision'] == 10
            mpanel.get_by_text('最近本人核对版本 10', exact=False).scroll_into_view_if_needed()
            assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            phone.screenshot(path=str(artifact/'mobile-review.png'), full_page=True, animations='disabled')
            phone.reload(); phone.get_by_role('tab', name='人工核对', exact=True).click()
            expect(mpanel.get_by_label('原始结果 1', exact=True)).to_have_value('手机端修正')
            mobile.close(); checks.append('新390px手机恢复；原件/核对切换保留填写；草稿及单独确认可操作，刷新保留服务端内容无横向溢出')
            imaging = upload('合成影像书面报告', 'imaging'); base = '/api/v1/patient/reports/'+imaging['id']
            page.goto(web+'/reports/'+imaging['id'])
            expect(panel.get_by_role('button', name='添加检验指标', exact=True)).not_to_be_visible()
            panel.get_by_role('button', name='添加报告文字', exact=True).click()
            panel.get_by_label('报告文字内容 1', exact=True).fill('合成书面所见，按原件录入')
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 1 已保存，尚未确认核对。', exact=True)).to_be_visible()
            confirm(page, panel)
            assert view()['confirmed']['content']['indicators'] == []
            checks.append('影像仅书面所见/结论，无检验数组仍能人工保存并确认，不生成医学解释')
            base = '/api/v1/patient/reports/'+os.environ['REPORTS_CANDIDATE_REPORT_ID']
            page.goto(web+'/reports/'+os.environ['REPORTS_CANDIDATE_REPORT_ID'])
            panel.get_by_role('button', name='从当前AI候选填写', exact=True).click()
            expect(panel.get_by_label('原始结果 1', exact=True)).to_have_value('6.2')
            panel.get_by_label('原始结果 1', exact=True).fill('7.1')
            panel.get_by_role('button', name='保存核对草稿', exact=True).click()
            expect(panel.get_by_text('草稿版本 1 已保存，尚未确认核对。', exact=True)).to_be_visible()
            confirm(page, panel)
            assert view()['confirmed']['content']['indicators'][0]['raw_value'] == '7.1'
            panel.get_by_role('button', name='查看核对历史', exact=True).click()
            panel.get_by_role('button', name='查看版本 2', exact=True).click()
            expect(panel.get_by_text('当时的AI原始候选（未核对）', exact=True)).to_be_visible()
            version_id = view()['confirmed']['id']
            historical = context.request.get(api+base+'/review/versions/'+version_id, headers=auth).json()
            assert historical['original_candidate']['indicators'][0]['raw_value'] == '6.2'
            checks.append('显式载入预置合成AI候选再人工修正；确认内容7.1、原始候选6.2独立保留可对照')
            assert not any(path.endswith('/ai') or path.endswith('/extract') for path, _ in paths)
            assert not errors, errors
            result = {'passed': checks, 'page_errors': errors, 'auth': 'synthetic JWT; actual login form not covered',
                'candidate': 'preseeded synthetic completed job; no external model'}
            (artifact/'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception:
            page.screenshot(path=str(artifact/'failure.png'), full_page=True, animations='disabled')
            (artifact/'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
            raise
        finally: browser.close()


if __name__ == '__main__': main()
