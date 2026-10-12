"""患者页外壳与档案标签回归：仅使用合成 API 和本地会话数据。"""
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, history, token
from today_health_browser import HealthAPI

ARTIFACTS = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-patient-shell-polish'


class ShellAPI(HealthAPI):
    def __init__(self):
        super().__init__()
        self.profile = {
            'id': 'shell-user', 'name': '林然', 'email': 'shell@example.test', 'height': 165, 'weight': 62.5, 'revision': 1,
            'section_states': {'allergies': 'present', 'conditions': 'present', 'medications': 'present'},
            'allergies': ['合成过敏源'],
            'chronic_diseases': [{'id': 'disease-a', 'name': '合成疾病记录', 'category': 'chronic', 'severity': 'moderate'}],
            'medications': [
                {'id': 'active-med', 'name': '合成药物 A', 'dosage': '原处方剂量', 'frequency': '原处方频率', 'status': 'active'},
                {'id': 'stopped-med', 'name': '合成药物 B', 'dosage': '', 'frequency': '', 'status': 'stopped'},
            ],
        }

    def route(self, route):
        if urlparse(route.request.url).path.endswith('/patient/measurements'):
            route.fulfill(status=200, json={'items': [], 'has_more': False})
        elif urlparse(route.request.url).path.endswith('/patient/profile') and route.request.method == 'GET':
            route.fulfill(status=200, json=self.profile)
        else:
            super().route(route)


def screenshot(page, name):
    page.wait_for_load_state('networkidle')
    page.screenshot(path=str(ARTIFACTS / name), full_page=True)


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            api = ShellAPI()
            context.route('**/api/v1/**', api.route)
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('jwt => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('shell-user'))
            page.goto(BASE + '/today')
            expect(page.get_by_role('heading', name='今日健康', exact=True)).to_be_visible()
            nav_y = page.get_by_role('button', name='今日健康', exact=True).bounding_box()['y']
            banner = page.get_by_role('banner', name='患者页顶部栏')
            header_height = banner.bounding_box()['height']

            page.goto(BASE + '/chat')
            expect(page.get_by_placeholder('描述您的症状，或补充检查报告…')).to_be_visible()
            expect(banner).to_contain_text('患者工作台')
            expect(banner).to_contain_text('AI 问诊')
            expect(banner).not_to_contain_text('医枢 MedAxis')
            expect(banner.get_by_role('link', name='查看提醒')).to_be_visible()
            assert banner.bounding_box()['height'] == header_height
            assert abs(page.get_by_role('button', name='今日健康', exact=True).bounding_box()['y'] - nav_y) < 1
            expect(page.locator('.MuiDrawer-root').get_by_role('button', name='新建会话', exact=True)).to_have_count(0)
            new_session = page.get_by_role('main').get_by_role('button', name='新建会话', exact=True)
            expect(new_session).to_be_visible()
            expect(page.get_by_role('button', name='新建会话', exact=True)).to_have_count(1)
            previous_id = history(page, 'user:shell-user')['currentSessionId']
            new_session.click()
            page.wait_for_function('JSON.parse(localStorage.getItem("medaxis.chat-history.v1:user:shell-user")).sessions.length === 2')
            saved = history(page, 'user:shell-user')
            assert saved['currentSessionId'] != previous_id
            assert previous_id in [session['id'] for session in saved['sessions']]
            page.reload()
            expect(new_session).to_be_enabled()
            assert history(page, 'user:shell-user')['currentSessionId'] == saved['currentSessionId']
            screenshot(page, 'chat-desktop.png')
            print('PASS: 侧栏主导航对齐、统一顶部栏、面板新建入口与会话保留/刷新恢复')

            page.goto(BASE + '/health')
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()
            expect(page.get_by_text('合成过敏源', exact=True)).to_have_css('color', 'rgb(190, 18, 60)')
            expect(page.get_by_text('慢性病', exact=True)).to_have_css('color', 'rgb(29, 78, 216)')
            expect(page.get_by_text('严重程度：中度', exact=True)).to_have_css('color', 'rgb(154, 52, 18)')
            expect(page.get_by_role('heading', name='正在服用（1 项）', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='已停用（1 项）', exact=True)).to_be_visible()
            screenshot(page, 'health-desktop.png')
            api.profile['allergies'] = []
            for state, label, color in [
                ('none', '明确无', 'rgb(29, 78, 216)'),
                ('unknown', '未知', 'rgb(154, 52, 18)'),
                ('not_recorded', '未填写', 'rgb(71, 85, 105)'),
            ]:
                api.profile['section_states']['allergies'] = state
                page.reload()
                state_chip = page.get_by_role('heading', name='过敏史', exact=True).locator('..').locator('.MuiChip-root')
                expect(state_chip).to_have_text(label)
                expect(state_chip).to_have_css('color', color)
            page.get_by_role('button', name='编辑档案', exact=True).click()
            expect(page.get_by_label('过敏史记录状态', exact=True)).to_have_text('未填写')
            page.get_by_role('button', name='取消', exact=True).click()
            print('PASS: 档案标签颜色与文字状态一致，未知/明确无/未填写仍可区分，编辑取消保留')

            api.profile['allergies'] = ['用于测试窄屏换行的合成过敏源' * 4]
            api.profile['section_states']['allergies'] = 'present'
            for width in [390, 320, 768]:
                page.set_viewport_size({'width': width, 'height': 844})
                page.goto(BASE + '/chat')
                expect(new_session).to_be_visible()
                summary = page.get_by_role('button', name='问诊摘要', exact=True)
                expect(summary).to_be_visible()
                new_box, summary_box = new_session.bounding_box(), summary.bounding_box()
                assert new_box['x'] + new_box['width'] <= summary_box['x']
                assert summary_box['x'] + summary_box['width'] <= width
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                new_session.click()
                expect(new_session).to_be_enabled()
                page.get_by_role('button', name='打开导航菜单', exact=True).click()
                expect(page.get_by_role('button', name='今日健康', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.locator('.MuiDrawer-root.MuiModal-root')).not_to_be_visible()
                if width == 390:
                    screenshot(page, 'chat-mobile.png')
                page.goto(BASE + '/health')
                expect(page.get_by_text(api.profile['allergies'][0], exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                if width == 390:
                    screenshot(page, 'health-mobile.png')
            assert not api.mutations, api.mutations
            page.evaluate('localStorage.clear()')
            page.goto(BASE + '/chat')
            expect(page.get_by_placeholder('描述您的症状，或补充检查报告…')).to_be_visible()
            expect(banner).to_contain_text('访客模式')
            expect(banner.get_by_role('link', name='患者工作台')).to_have_count(0)
            expect(banner.get_by_role('link', name='查看提醒')).to_have_count(0)
            expect(new_session).to_be_enabled()
            assert not errors, errors
            print('PASS: 320/390/768px 入口无遮挡、长标签换行、移动导航与访客边界；无运行时异常')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
