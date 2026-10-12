"""问诊侧栏回归：复用 mock SSE，只使用合成数据，不写数据库。

先启动 Vite 127.0.0.1:3001，再运行 python tests/consultation_sidebar_browser.py。
截图默认写入临时目录，可设置 CONSULTATION_SCREENSHOT_DIR。
"""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, REPORT, events, ready, reload, send, token


class SidebarAPI(MockAPI):
    def route(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path == '/api/v1/consultations' or path == '/api/v1/consultations/doctors':
            route.fulfill(status=200, json={'items': [], 'has_more': False})
            return
        if path.startswith('/api/v1/consultations/preview/'):
            route.fulfill(status=200, json={'source_fingerprint': 'a' * 64, 'case_title': '合成问诊', 'ai_summary': '合成摘要', 'materials': []})
            return
        if urlparse(request.url).path.endswith('/route/stream'):
            # 当前入口使用 POST 请求体；共享旧回归 mock 仍假设 GET query。
            assert request.method == 'POST'
            label = request.post_data_json['message']
            body = events(
                ('text', {'text': f'已记录：{label}'}),
                ('question', {'question_id': 'q1', 'questions': [
                    {'question_id': 'q1', 'question': '持续多久？', 'type': 'choice', 'options': ['一天', '两天']},
                    {'question_id': 'q2', 'question': '程度如何？', 'type': 'choice', 'options': ['轻微', '严重']},
                ]}),
                ('complete', {'status': 'waiting_for_answer', 'session_id': f'backend-{label}'}),
            )
            route.fulfill(status=200, content_type='text/event-stream', body=body)
            return
        super().route(route)


def main():
    REPORT.update({
        'key_findings': ['合成数据：血压 135/85 mmHg', '合成数据：睡眠约 6 小时'],
        'recommended_actions': ['合成建议：记录症状变化', '合成建议：与医生讨论'],
        'follow_up_timeline': '合成建议：三天后复查',
    })
    artifacts = Path(os.getenv('CONSULTATION_SCREENSHOT_DIR', tempfile.gettempdir()))
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            api = SidebarAPI()
            context.route('**/api/v1/**', api.route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('(jwt) => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('sidebar-test'))
            page.goto(f'{BASE}/chat')
            ready(page)
            rail = page.get_by_role('complementary', name='问诊辅助信息')
            expect(rail).to_be_visible()
            for title in ['本次问诊摘要', '安全提示', '接下来可以做什么', '需要专业帮助？']:
                expect(rail.get_by_role('heading', name=title, exact=True)).to_be_visible()
            expect(rail).not_to_contain_text('135/85')
            send(page, '合成主诉：最近一周头痛')
            expect(rail).to_contain_text('合成主诉：最近一周头痛')
            page.get_by_role('button', name='一天', exact=True).click()
            expect(page.get_by_role('button', name='轻微', exact=True)).to_be_enabled()
            ready(page)
            page.get_by_role('button', name='轻微', exact=True).click()
            page.get_by_role('button', name='关闭问诊总结', exact=True).click()
            expect(rail).to_contain_text('血压 135/85 mmHg')
            expect(rail.get_by_role('region', name='安全提示')).to_contain_text('测试危险信号')
            expect(rail).to_contain_text('三天后复查')
            expect(rail).to_contain_text('需关注')
            main_box = page.get_by_role('main').bounding_box()
            rail_box = rail.bounding_box()
            assert main_box['x'] + main_box['width'] <= rail_box['x']
            rail.get_by_role('button', name='查看完整总结与来源').click()
            expect(page.get_by_role('dialog')).to_contain_text('这次问诊总结')
            page.get_by_role('button', name='关闭问诊总结', exact=True).click()
            page.screenshot(path=str(artifacts / 'medaxis-consultation-sidebar-desktop.png'))
            rail.get_by_role('button', name='转接真实医生').click()
            expect(page.get_by_role('dialog', name='转接真实医生')).to_contain_text('选择医生')
            expect(page.get_by_role('button', name='确认转接', exact=True)).to_be_disabled()
            assert urlparse(page.url).path == '/chat'
            page.get_by_role('button', name='取消', exact=True).click()
            reload(page)
            ready(page)
            expect(rail).to_contain_text('血压 135/85 mmHg')
            send(page, '合成补充：今天症状变化')
            expect(rail).to_contain_text('补充：合成补充：今天症状变化')
            expect(rail.get_by_role('status')).to_contain_text('新补充尚未纳入评估')
            ready(page)
            print('PASS: 桌面四卡、会话更新、报告来源、转接医生原地弹窗与刷新恢复')

            for width in [1024, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 844})
                expect(rail).to_have_count(0)
                summary_button = page.get_by_role('button', name='问诊摘要', exact=True)
                expect(summary_button).to_be_visible()
                summary_button.click()
                expect(rail).to_be_visible()
                expect(page.get_by_role('dialog', name='问诊辅助信息')).to_have_css('transform', 'none')
                expect(rail).to_contain_text('血压 135/85 mmHg')
                if width == 390:
                    page.screenshot(path=str(artifacts / 'medaxis-consultation-sidebar-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.keyboard.press('Escape')
                expect(rail).to_have_count(0)
                expect(summary_button).to_be_focused()
                expect(page.get_by_placeholder('描述您的症状，或补充检查报告…')).to_be_visible()
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.get_by_role('button', name='新建会话', exact=True).last.click()
            expect(rail).not_to_contain_text('135/85')
            expect(rail).not_to_contain_text('测试危险信号')
            rail.get_by_role('button', name='转接真实医生').click()
            expect(page.get_by_role('dialog', name='转接真实医生')).to_contain_text('请先完成并保存本次问诊')
            page.get_by_role('button', name='继续问诊', exact=True).click()
            assert not errors, errors
            print('PASS: 平板与 390/320 窄屏抽屉、无横向溢出、Esc 与焦点恢复、会话隔离')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
