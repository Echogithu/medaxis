"""浏览器使用真实隔离 API，覆盖保存恢复、失败保留、冲突与手机布局。"""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

def main():
    api, web = os.environ['PROFILE_API_URL'], os.environ['PROFILE_WEB_URL']
    for target in [api, web]:
        parsed = urlsplit(target)
        assert parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}
    assert urlsplit(os.environ['DATABASE_URL']).path.startswith('/medaxis_demo_e2e_')
    jwt = os.environ['PROFILE_BROWSER_TOKEN']
    artifact = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-health-followup-workspace/profile'
    cases, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1050})
        mode = {'fail': False, 'measurement_lost': False}
        def bridge(route):
            if route.request.method == 'POST' and urlsplit(route.request.url).path.endswith('/measurements') and mode['measurement_lost']:
                mode['measurement_lost'] = False
                response = route.fetch(url=api + urlsplit(route.request.url).path)
                assert response.status == 201
                return route.fulfill(status=500, json={'detail': '合成指标保存响应丢失'})
            if route.request.method == 'PATCH' and mode['fail']:
                mode['fail'] = False
                return route.fulfill(status=500, json={'detail': 'synthetic one-shot failure'})
            path = urlsplit(route.request.url).path
            query = urlsplit(route.request.url).query
            response = route.fetch(url=f'{api}{path}' + (f'?{query}' if query else ''))
            route.fulfill(response=response)
        context.route('**/api/v1/**', bridge)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        def select(label, choice):
            page.get_by_role('combobox', name=label, exact=True).click()
            page.get_by_role('option', name=choice, exact=True).click()
        def saved():
            expect(page.get_by_role('button', name='编辑档案', exact=True)).to_be_visible()
        try:
            page.goto(web)
            page.evaluate("token => { localStorage.setItem('access_token', token); localStorage.setItem('user_role', 'patient'); }", jwt)
            page.goto(f'{web}/health')
            saved()
            expect(page.get_by_text('档案更新时间未记录', exact=True)).to_be_visible()
            assert page.get_by_text('未填写', exact=True).count() >= 3
            cases.append('空档案不被解释为明确无')
            page.get_by_role('button', name='编辑档案', exact=True).click()
            select('过敏史记录状态', '未知')
            page.get_by_role('button', name='添加疾病', exact=True).click()
            page.get_by_label('疾病名称', exact=True).fill('合成特殊疾病')
            select('疾病分类', '特殊疾病')
            select('严重程度', '重度')
            page.get_by_label('确诊日期（可留空）', exact=True).fill('2020-01-02')
            page.get_by_label('备注说明', exact=True).fill('仅用于验收的患者自报说明')
            page.get_by_role('button', name='添加药物', exact=True).click()
            page.get_by_label('药物名称', exact=True).fill('合成停用药物')
            select('用药状态', '已停用')
            page.get_by_role('button', name='保存', exact=True).click()
            saved()
            expect(page.get_by_text('合成特殊疾病', exact=True).last).to_be_visible()
            expect(page.get_by_text('严重程度：重度', exact=True)).to_be_visible()
            expect(page.get_by_text('确诊日期：2020-01-02', exact=True)).to_be_visible()
            expect(page.get_by_text('已停用', exact=True)).to_be_visible()
            auth = {'Authorization': f'Bearer {jwt}'}
            result = context.request.get(f'{api}/api/v1/patient/profile', headers=auth)
            assert result.status == 200
            profile = result.json()
            assert profile['revision'] == 1 and profile['section_states']['allergies'] == 'unknown'
            assert profile['chronic_diseases'][0]['source'] == 'patient_reported'
            assert profile['chronic_diseases'][0]['updated_at'] and profile['updated_at']
            assert profile['chronic_diseases'][0]['notes'] == '仅用于验收的患者自报说明'
            assert profile['medications'][0]['status'] == 'stopped'
            page.reload()
            saved()
            expect(page.get_by_text('仅用于验收的患者自报说明', exact=True)).to_be_visible()
            sources = page.get_by_text(re.compile('^患者自报 · 更新时间：'))
            expect(sources.first).to_be_visible()
            assert sources.count() >= 3
            assert all('未记录' not in text for text in sources.all_text_contents())
            page.screenshot(path=str(artifact / 'health-profile-desktop.png'), full_page=True)
            cases.append('疾病分类、严重程度、日期、备注、来源、用药停用状态保存并刷新恢复')
            page.get_by_role('button', name='编辑档案', exact=True).click()
            page.get_by_label('备注说明', exact=True).fill('服务器失败后应保留的草稿')
            mode['fail'] = True
            page.get_by_role('button', name='保存', exact=True).click()
            expect(page.get_by_text('保存失败，请检查记录内容或网络后重试；当前修改仍保留。', exact=True)).to_be_visible()
            expect(page.get_by_label('备注说明', exact=True)).to_have_value('服务器失败后应保留的草稿')
            page.get_by_role('button', name='保存', exact=True).click()
            saved()
            cases.append('500 失败保留草稿并可重试保存')
            page.get_by_role('button', name='编辑档案', exact=True).click()
            page.get_by_label('备注说明', exact=True).fill('并发冲突应保留的草稿')
            current = context.request.get(f'{api}/api/v1/patient/profile', headers=auth).json()
            external = context.request.patch(f'{api}/api/v1/patient/profile', headers=auth,
                data={'expected_revision': current['revision'], 'phone': '13800000000'})
            assert external.status == 200
            page.get_by_role('button', name='保存', exact=True).click()
            expect(page.get_by_label('备注说明', exact=True)).to_have_value('并发冲突应保留的草稿')
            expect(page.get_by_role('button', name='重新加载并退出编辑', exact=True)).to_be_visible()
            persisted = context.request.get(f'{api}/api/v1/patient/profile', headers=auth).json()
            assert persisted['chronic_diseases'][0]['notes'] == '服务器失败后应保留的草稿'
            page.get_by_role('button', name='重新加载并退出编辑', exact=True).click()
            saved()
            expect(page.get_by_text('13800000000', exact=True)).to_be_visible()
            cases.append('409 冲突不覆盖档案，保留草稿并可重新加载')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.get_by_text('合成特殊疾病', exact=True).last.scroll_into_view_if_needed()
            page.screenshot(path=str(artifact / 'health-profile-mobile.png'), full_page=True)
            page.get_by_role('button', name='编辑档案', exact=True).click()
            page.get_by_label('疾病名称', exact=True).fill('')
            page.get_by_role('button', name='保存', exact=True).click()
            expect(page.get_by_text('请填写疾病和药物名称，或删除空白条目；当前修改仍保留。', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            cases.append('390px 手机布局无横向溢出，空疾病名称禁止保存')
            page.get_by_label('疾病名称', exact=True).fill('合成特殊疾病')
            page.get_by_label('确诊日期（可留空）', exact=True).fill('2999-01-01')
            page.get_by_role('button', name='保存', exact=True).click()
            expect(page.get_by_text('确诊日期不能晚于今天；当前修改仍保留。', exact=True)).to_be_visible()
            cases.append('未来确诊日期在提交前明确提示，草稿保留')
            page.get_by_role('button', name='取消', exact=True).click()
            page.get_by_role('button', name='记录健康指标', exact=True).click()
            measure = page.get_by_role('dialog', name='记录健康指标')
            measure.get_by_role('button', name='保存记录', exact=True).click()
            expect(measure.get_by_text('请至少填写一项健康指标', exact=True)).to_be_visible()
            measure.get_by_label('收缩压（mmHg）', exact=True).fill('128')
            measure.get_by_role('button', name='保存记录', exact=True).click()
            expect(measure.get_by_text('血压需同时填写收缩压与舒张压', exact=True)).to_be_visible()
            measure.get_by_label('舒张压（mmHg）', exact=True).fill('82')
            measure.get_by_label('静息心率（次/分）', exact=True).fill('68')
            measure.get_by_label('体重（kg）', exact=True).fill('62.5')
            before_measure = context.request.get(f'{api}/api/v1/patient/profile', headers=auth).json()
            mode['measurement_lost'] = True
            measure.get_by_role('button', name='保存记录', exact=True).click()
            expect(measure.get_by_role('alert')).to_contain_text('合成指标保存响应丢失')
            expect(measure.get_by_label('体重（kg）', exact=True)).to_have_value('62.5')
            measure.get_by_role('button', name='保存记录', exact=True).click()
            expect(measure).not_to_be_visible()
            page.reload()
            expect(page.get_by_text('128/82', exact=True)).to_be_visible()
            stored = context.request.get(f'{api}/api/v1/patient/measurements', headers=auth).json()
            assert len(stored['items']) == 1 and stored['items'][0]['weight'] == 62.5
            after_measure = context.request.get(f'{api}/api/v1/patient/profile', headers=auth).json()
            assert before_measure['revision'] == after_measure['revision'] and before_measure['weight'] == after_measure['weight']
            cases.append('健康指标真实保存、刷新恢复、响应丢失重试只一条；不覆盖基础体重或档案版本')
            page.set_viewport_size({'width':1440,'height':1050})
            page.get_by_role('main').evaluate('e => e.scrollTop = 0')
            page.screenshot(path=str(artifact / 'health-workspace-desktop.png'), full_page=True)
            for width in [390, 320, 768]:
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifact / 'health-workspace-mobile.png'), full_page=True)
            page.evaluate("token => localStorage.setItem('access_token', token)", os.environ['PROFILE_LEGACY_TOKEN'])
            page.reload()
            saved()
            expect(page.get_by_text('档案更新时间未记录', exact=True)).to_be_visible()
            legacy_sources = page.get_by_text('历史记录，来源未记录 · 更新时间：未记录', exact=True)
            assert legacy_sources.count() >= 3
            legacy_sources.last.scroll_into_view_if_needed()
            expect(legacy_sources.last).to_be_visible()
            cases.append('页面展示患者自报的有效时间及旧记录来源/时间未记录')
            assert not errors, errors
            (artifact / 'browser-profile-results.json').write_text(json.dumps({'passed': cases, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': cases, 'page_errors': errors}, ensure_ascii=False), flush=True)
        finally:
            context.close()
            browser.close()


if __name__ == '__main__':
    main()
