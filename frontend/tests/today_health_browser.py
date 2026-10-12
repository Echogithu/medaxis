"""患者工作台设计回归。API 全部 mock，不连接数据库或问诊模型。

从 frontend 运行：CHAT_TEST_URL 指向本地 Vite，再执行 python tests/today_health_browser.py。
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, token

ARTIFACTS = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-02-patient-design-refresh'
TODAY = datetime.now(timezone(timedelta(hours=8))).date().isoformat()


class HealthAPI(MockAPI):
    def __init__(self):
        super().__init__()
        self.empty = False
        self.failed = False
        self.failed_section = ''
        self.medication_state = ''
        self.partial = False
        self.mutations = []
        self.reminders = [
            {'id': 'med-a', 'event_type': 'medication_reminder', 'payload': {'name': '合成药物 A', 'dosage': '原处方剂量'},
             'scheduled_at': TODAY + 'T08:00:00+08:00', 'status': 'sent', 'acknowledged_at': None},
            {'id': 'med-b', 'event_type': 'medication_reminder', 'payload': {'name': '合成药物 B'},
             'scheduled_at': TODAY + 'T20:00:00+08:00', 'status': 'pending', 'acknowledged_at': None},
        ]

    def route(self, route):
        request = route.request
        path = urlparse(request.url).path
        query = parse_qs(urlparse(request.url).query)
        if request.method != 'GET':
            self.mutations.append((request.method, path))
        if (self.failed and any(path.endswith(suffix) for suffix in ['/patient/profile', '/patient/care-plans', '/patient/reminders', '/patient/cases'])) or (self.failed_section and path.endswith(self.failed_section)):
            route.fulfill(status=503, json={'detail': '合成服务异常'})
            return
        if path.endswith('/auth/login'):
            data = {'access_token': token('design-user'), 'user': {'id': 'design-user', 'role': 'patient'}}
        elif path.endswith('/patient/profile'):
            data = {'id': 'design-user', 'name': '林然', 'email': 'design@example.test', 'height': 165, 'weight': 62.5, 'revision': 1,
                    'medications': [] if self.empty else [{'name': '合成药物 A', 'dosage': '原处方剂量', 'frequency': '原处方频率', 'status': 'active'}],
                    'allergies': [], 'chronic_diseases': [], 'section_states': {'allergies': 'unknown', 'conditions': 'not_recorded', 'medications': 'none' if self.empty else 'present'}}
            if self.medication_state:
                data['medications'] = []
                data['section_states']['medications'] = self.medication_state
        elif path.endswith('/patient/reminders/count'):
            data = {'follow_up': 1, 'medication': 1, 'total': 2}
        elif path.endswith('/patient/reminders'):
            assert int(query['limit'][0]) <= 50
            data = {'items': [] if self.empty else self.reminders,
                    'next_cursor': {'scheduled_at': TODAY + 'T08:00:00+08:00', 'id': 'med-a'} if self.partial else None}
        elif path.endswith('/med-a/acknowledge'):
            self.reminders[0]['status'] = 'acknowledged'
            self.reminders[0]['acknowledged_at'] = TODAY + 'T08:10:00+08:00'
            data = {'success': True, 'id': 'med-a', 'status': 'acknowledged', 'acknowledged_at': self.reminders[0]['acknowledged_at']}
        elif path.endswith('/patient/care-plans'):
            assert int(query.get('limit', ['10'])[0]) <= 50
            plan = {'id': 'plan-a', 'title': '本周照护计划', 'revision': 1, 'status': 'active', 'effective_status': 'active',
                    'can_execute': True, 'source_type': 'patient_reported', 'start_date': TODAY, 'end_date': TODAY,
                    'progress_percent': 50, 'tasks': [
                        {'id': 'task-a', 'description': '记录今日健康情况', 'due_date': TODAY, 'status': 'completed', 'type': 'self_check'},
                        {'id': 'task-b', 'description': '准备本周复查资料', 'due_date': TODAY, 'status': 'pending', 'type': 'follow_up'},
                    ]}
            data = {'items': [] if self.empty else [plan], 'next_cursor': None}
        elif path.endswith('/patient/ai-actions/pending'):
            data = {'items': []}
        elif path.endswith('/patient/cases') and self.empty:
            data = []
        else:
            return super().route(route)
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data, ensure_ascii=False))


def screenshot(page, name):
    page.wait_for_load_state('networkidle')
    page.screenshot(path=str(ARTIFACTS / name), full_page=True)


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            api = HealthAPI()
            context.route('**/api/v1/**', api.route)
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('jwt => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('design-user'))
            page.goto(BASE + '/')
            expect(page).to_have_url(BASE + '/today')
            expect(page.get_by_role('heading', name='今日健康', exact=True)).to_be_visible()
            expect(page.get_by_text('已记录 1 / 4 项', exact=True)).to_be_visible()
            expect(page.get_by_text('62.5', exact=False)).to_be_visible()
            assert not api.mutations
            screenshot(page, 'today-desktop.png')
            page.get_by_role('link', name='开始 AI 问诊', exact=True).click()
            expect(page.get_by_placeholder('描述您的症状，或补充检查报告…')).to_be_visible()
            screenshot(page, 'chat-desktop.png')

            page.goto(BASE + '/reminders')
            expect(page.get_by_role('button', name='我已服用', exact=True)).to_be_visible()
            page.get_by_role('button', name='我已服用', exact=True).click()
            expect(page.get_by_text('已打卡（患者自报）', exact=False)).to_be_visible()
            page.goto(BASE + '/today')
            expect(page.get_by_text('已记录 2 / 4 项', exact=True)).to_be_visible()
            api.medication_state = 'unknown'
            page.goto(BASE + '/today')
            expect(page.get_by_role('link').filter(has=page.get_by_text('当前用药', exact=True))).to_contain_text('—')
            api.medication_state = ''
            print('PASS: 首页真实字段、UTC+8 今日归类、入口导航与原用药页打卡后刷新同步')

            page.goto(BASE + '/health')
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()
            page.get_by_role('button', name='编辑档案', exact=True).click()
            expect(page.get_by_label('姓名', exact=True)).to_have_value('林然')
            page.get_by_role('button', name='取消', exact=True).click()
            screenshot(page, 'health-desktop.png')
            page.goto(BASE + '/followups')
            expect(page.get_by_role('heading', name='本周照护计划', exact=True)).to_be_visible()
            page.get_by_role('button', name='新建随访计划', exact=True).click()
            expect(page.get_by_role('dialog', name='新建随访计划')).to_be_visible()
            page.get_by_role('button', name='关闭', exact=True).click()
            screenshot(page, 'followups-desktop.png')
            print('PASS: 档案编辑/取消与随访新建入口保留')

            api.empty = True
            page.goto(BASE + '/today')
            expect(page.get_by_text('今天暂无照护安排', exact=True)).to_be_visible()
            expect(page.get_by_text('还没有问诊记录', exact=True)).to_be_visible()
            page.goto(BASE + '/reminders')
            expect(page.get_by_text('暂无用药提醒', exact=True)).to_be_visible()
            text = page.locator('body').inner_text()
            for redundant in ['这里只显示已安排', '当前已加载记录中', '可在问诊记录中保存就诊结果']:
                assert redundant not in text, redundant
            screenshot(page, 'reminders-empty-desktop.png')
            page.get_by_role('link', name='查看用药清单', exact=True).click()
            expect(page).to_have_url(BASE + '/health')
            expect(page.get_by_role('heading', name='健康档案', exact=True)).to_be_visible()

            api.failed = True
            page.goto(BASE + '/today')
            expect(page.get_by_role('alert')).to_contain_text('暂时无法加载')
            expect(page.get_by_text('今天暂无照护安排', exact=True)).to_have_count(0)
            expect(page.get_by_text('还没有问诊记录', exact=True)).to_have_count(0)
            api.failed = False
            page.get_by_role('button', name='重试', exact=True).click()
            expect(page.get_by_text('今天暂无照护安排', exact=True)).to_be_visible()
            api.partial = True
            page.goto(BASE + '/today')
            expect(page.get_by_text('部分记录', exact=True)).to_be_visible()
            expect(page.get_by_text('今天暂无照护安排', exact=True)).to_have_count(0)
            print('PASS: 空状态无冗余文案，加载失败可重试，分页预览不伪装全量数据')

            api.empty = False
            api.partial = False
            api.failed_section = '/patient/reminders'
            page.goto(BASE + '/today')
            expect(page.get_by_role('alert')).to_contain_text('用药提醒暂时无法加载')
            expect(page.get_by_text('已记录 1 / 2 项', exact=True)).to_be_visible()
            expect(page.get_by_text('50%', exact=True)).to_have_count(0)
            expect(page.get_by_text('62.5', exact=False)).to_be_visible()
            api.failed_section = ''
            print('PASS: 未知用药不显示零，单个请求失败保留其余数据并隐藏全量完成率')
            for width in [390, 320, 768]:
                page.set_viewport_size({'width': width, 'height': 844})
                page.goto(BASE + '/today')
                expect(page.get_by_role('navigation', name='移动端导航')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                if width == 390:
                    screenshot(page, 'today-mobile.png')
                for path in ['/health', '/followups', '/reminders', '/cases?case_id=demo-case-a', '/chat']:
                    page.goto(BASE + path)
                    page.wait_for_load_state('networkidle')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, path)
                composer = page.get_by_placeholder('描述您的症状，或补充检查报告…')
                nav = page.get_by_role('navigation', name='移动端导航')
                assert composer.bounding_box()['y'] + composer.bounding_box()['height'] <= nav.bounding_box()['y']
                nav.get_by_role('button', name='更多功能', exact=True).click()
                dialog = page.get_by_role('dialog', name='更多功能')
                expect(dialog).to_be_visible()
                dialog.get_by_role('button', name='用药提醒', exact=True).click()
                expect(page).to_have_url(BASE + '/reminders')
                expect(page.get_by_role('heading', name='用药提醒', exact=True)).to_be_visible()
                if width == 390:
                    screenshot(page, 'reminders-mobile.png')
            assert api.mutations == [('PATCH', '/api/v1/patient/reminders/med-a/acknowledge')], api.mutations
            print('PASS: 320/390/768px 全患者页无横向溢出，导航无遮挡输入，更多弹层与运行时异常检查')
            page.evaluate('localStorage.clear()')
            page.goto(BASE + '/today')
            expect(page).to_have_url(BASE + '/login')
            page.get_by_label('邮箱地址', exact=False).fill('design@example.test')
            page.locator('#password-input').fill('synthetic-password')
            page.get_by_role('button', name='登录', exact=True).click()
            expect(page).to_have_url(BASE + '/today')
            expect(page.get_by_role('heading', name='今日健康', exact=True)).to_be_visible()
            page.evaluate('localStorage.clear()')
            page.goto(BASE + '/login')
            page.get_by_role('button', name='以访客身份体验', exact=True).click()
            expect(page).to_have_url(BASE + '/chat')
            expect(page.get_by_placeholder('描述您的症状，或补充检查报告…')).to_be_visible()
            expect(page.get_by_role('navigation', name='移动端导航')).to_have_count(0)
            assert not errors, errors
            print('PASS: 未登录首页守卫、患者登录后进入今日健康、访客问诊入口')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
