"""延迟模块与身份请求，验证患者外壳保留及内容区加载。合成 API。"""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from patient_shell_browser import ShellAPI
from chat_history_browser import BASE, history, token

ARTIFACT = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-patient-shell-doctor-consultations'


def main():
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            errors, documents, observed = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: documents.append(r.url) if r.resource_type == 'document' else None)
            api, flags = ShellAPI(), {'check_auth': False}
            def check_shell():
                assert page.evaluate("window.shellHeader === document.querySelector('header[aria-label=\"患者页顶部栏\"]') && window.shellDrawer === document.querySelector('.MuiDrawer-root')")
                expect(page.get_by_role('banner', name='患者页顶部栏')).to_be_visible()
                expect(page.get_by_role('button', name='今日健康', exact=True)).to_be_visible()
            def api_route(route):
                if flags['check_auth'] and urlsplit(route.request.url).path.endswith('/auth/me'):
                    check_shell()
                    expect(page.get_by_label('加载会话历史', exact=True)).to_be_visible()
                    observed.append('身份加载保留外壳')
                api.route(route)
            context.route('**/api/v1/**', api_route)
            def lazy_route(route):
                check_shell()
                expect(page.get_by_label('加载页面内容', exact=True)).to_be_visible()
                observed.append('模块加载限定内容区')
                route.continue_()
            page.goto(BASE)
            page.evaluate('jwt => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('shell-user'))
            page.goto(BASE + '/today')
            expect(page.get_by_role('heading', name='今日健康', exact=True)).to_be_visible()
            page.evaluate("window.shellHeader = document.querySelector('header[aria-label=\"患者页顶部栏\"]'); window.shellDrawer = document.querySelector('.MuiDrawer-root');")
            count = len(documents)
            context.route('**/src/components/ChatHistoryPage.tsx*', lazy_route)
            flags['check_auth'] = True
            page.get_by_role('button', name='AI 问诊', exact=True).click()
            field = page.get_by_placeholder('描述您的症状，或补充检查报告…')
            expect(field).to_be_visible()
            flags['check_auth'] = False
            check_shell()
            assert len(documents) == count
            assert set(observed) == {'模块加载限定内容区', '身份加载保留外壳'}
            previous = history(page, 'user:shell-user')['currentSessionId']
            page.get_by_role('button', name='新建会话', exact=True).click()
            current = history(page, 'user:shell-user')['currentSessionId']
            assert previous != current
            page.get_by_role('button', name='健康档案', exact=True).click()
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()
            check_shell()
            page.get_by_role('button', name='AI 问诊', exact=True).click()
            expect(field).to_be_visible()
            assert history(page, 'user:shell-user')['currentSessionId'] == current
            check_shell()
            assert len(documents) == count and not errors, errors
            page.screenshot(path=str(ARTIFACT / 'shared-patient-shell.png'))
            print('PASS: 路由切换无 document 请求；侧栏与 header DOM 保留；延迟模块及身份请求仅加载内容区；往返会话历史保留；无运行时错误')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
