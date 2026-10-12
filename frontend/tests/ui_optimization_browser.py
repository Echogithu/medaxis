"""患者与管理员界面回归；全部接口为合成数据，不访问数据库或模型。"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect
from chat_history_browser import BASE, token
from patient_shell_browser import ShellAPI
from today_health_browser import TODAY
from patient_records_browser import RecordsAPI

STAMP = '2026-10-08T08:00:00Z'
REPORT = dict(id='synthetic-report', title='合成检查报告', category='lab', institution='合成机构',
              examination_date='2026-10-07', report_date='2026-10-07', notes='仅用于界面审查',
              revision=1, source_version=1, created_at=STAMP, updated_at=STAMP, ownership_declared=True,
              source='patient_uploaded', archive_status='active', extraction_status='not_started',
              review_status='unreviewed', file_count=0, page_count=0, files=[], ai_status='not_started',
              lifecycle_revision=1, trashed_at=None)
USER = dict(id='synthetic-admin', email='admin@example.test', full_name='合成管理员', role='admin',
            status='active', is_verified=True, license_number=None, hospital=None, department=None,
            title=None, created_at=STAMP, updated_at=STAMP, last_login_at=STAMP)
DOCTOR = dict(USER, id='synthetic-doctor', email='doctor@example.test', full_name='合成医生',
              role='doctor', is_verified=False, license_number='SYNTHETIC', hospital='合成机构', department='合成科室')


class AuditAPI:
    def __init__(self):
        self.role = 'patient'
        self.health = ShellAPI()
        self.records = RecordsAPI()
        self.calls = []
        self.failed = ''

    def route(self, route):
        req = route.request
        path = urlparse(req.url).path.rstrip('/')
        query = parse_qs(urlparse(req.url).query)
        self.calls.append({'method': req.method, 'path': path, 'query': query})
        if req.method != 'GET':
            route.fulfill(status=405, json={'detail': '审查模式不执行写操作'})
            return
        if path == self.failed:
            route.fulfill(status=503, json={'detail': '合成网络失败'})
            return
        if path.endswith('/auth/me'):
            data = dict(USER, role=self.role)
        elif path.endswith('/patient/reports'):
            data = {'items': [REPORT], 'total': 1, 'page': 1, 'limit': 12,
                    'stats': {'archived': 1, 'pending_review': 1, 'latest_examination_date': '2026-10-07', 'trashed': 0}}
        elif path.endswith('/patient/reports/synthetic-report'):
            data = REPORT
        elif path.endswith('/patient/reports/synthetic-report/lifecycle'):
            data = {'report': REPORT, 'state_token': 'synthetic-state', 'links_count': 0,
                    'pending_jobs': 0, 'has_dispatched_text': False}
        elif path.endswith('/patient/reports/synthetic-report/workspace'):
            data = {'revision': 1, 'source_version': 1, 'category': 'lab', 'extract_job': None, 'ai_job': None, 'preview': None}
        elif path.endswith('/patient/reports/synthetic-report/review'):
            data = {'revision': 1, 'source_epoch': 1, 'source_version': 1, 'source_hash': 'synthetic', 'category': 'lab',
                    'review_status': 'unreviewed', 'confirmed_at': None, 'draft': None, 'confirmed': None, 'candidate': None}
        elif path.endswith('/patient/reports/synthetic-report/review/history'):
            data = {'items': [], 'total': 0, 'page': 1, 'limit': 20}
        elif path.endswith('/patient/reports/synthetic-report/case-links'):
            data = {'items': [], 'links_revision': 1, 'review_revision': 1, 'source_epoch': 1,
                    'source_hash': 'synthetic', 'source_version': 1, 'current_review_version_id': None}
        elif '/patient/cases' in path:
            return self.records.route(route)
        elif path.endswith('/admin/dashboard/stats'):
            data = {'users': {'total': 142, 'by_role': {'patient': 120, 'doctor': 20, 'admin': 2}},
                    'llm_providers': {'total': 1, 'active': 1}, 'system_settings': 2, 'timestamp': STAMP}
        elif path.endswith('/admin/users'):
            data = [USER, DOCTOR]
        elif path.endswith('/admin/doctors'):
            data = [DOCTOR]
        elif path.endswith('/admin/llm-providers'):
            data = [dict(id='synthetic-provider', provider='custom', platform=None, name='合成模型服务',
                         base_url='https://model.example.test/v1', default_model='synthetic-model', model_type='diagnosis',
                         is_active=True, is_default=True, api_key_masked='***', created_at=STAMP, updated_at=STAMP)]
        elif path.endswith('/admin/settings'):
            data = [dict(id='synthetic-setting', key='site_name', value='合成 MedAxis', description='站点名称',
                         is_sensitive=False, category='general', value_type='string', options=None, created_at=STAMP, updated_at=STAMP)]
        elif path.endswith('/admin/knowledge/reviews'):
            data = [dict(id='synthetic-doc', title='合成参考资料', doc_type='case_report', review_status='pending',
                         uploaded_by='synthetic-doctor', created_at=STAMP, agent_review_score=None, agent_review_notes=None)]
        elif path.endswith('/admin/knowledge'):
            data = [dict(id='synthetic-doc', title='合成参考资料', doc_type='case_report', source_type='internal',
                         review_status='pending', department='合成科室', disease_tags=[], drug_name=None, is_active=True,
                         is_featured=False, chunk_count=1, vectorized_at=None, created_at=STAMP, updated_at=STAMP)]
        elif path.endswith('/admin/audit-logs/stats/overview'):
            data = {'total_today': 1, 'total_week': 1, 'failed_today': 1, 'action_breakdown': [{'action': 'LOGIN', 'count': 1}]}
        elif path.endswith('/admin/audit-logs'):
            data = [dict(id='synthetic-log', user_id=USER['id'], user_email=USER['email'], user_role='admin', action='LOGIN',
                         resource_type='USER', resource_id=USER['id'], details={}, ip_address='127.0.0.1', user_agent=None,
                         success=False, error_message='合成错误', created_at=STAMP)]
        elif path.endswith('/admin/notifications/unread-count'):
            data = {'total': 1, 'system': 0, 'announcement': 1, 'direct': 0, 'reminder': 0}
        elif path.endswith('/admin/notifications'):
            data = {'items': [dict(id='synthetic-notice', notification_type='announcement', priority='high',
                                  subject='合成系统通知', content_preview='仅用于界面审查', is_read=False,
                                  read_at=None, broadcast=True, sender=None, created_at=STAMP)],
                    'total': 45, 'page': int(query.get('page', ['1'])[0]), 'page_size': 20, 'total_pages': 3, 'unread_count': 1}
        elif path.endswith('/admin/email/configs') or path.endswith('/admin/email/templates'):
            data = {'items': [], 'total': 0}
        elif path.endswith('/admin/email/logs'):
            data = {'items': [], 'total': 0, 'page': 1, 'page_size': 20, 'total_pages': 0}
        elif path.endswith('/admin/email/providers'):
            data = {'providers': [], 'categories': []}
        elif '/admin/' in path:
            route.fulfill(status=404, json={'detail': '未配置的合成接口'})
            return
        else:
            return self.health.route(route)
        if path.endswith(('/admin/knowledge', '/admin/knowledge/reviews', '/admin/audit-logs')):
            count = 45 if path.endswith('/audit-logs') else 23
            first = data[0]
            data = [dict(first, id=f"{first['id']}-{i}", **({'title': f'合成参考资料 {i}'} if 'title' in first else {})) for i in range(count)]
            offset, limit = int(query.get('skip', ['0'])[0]), int(query.get('limit', ['20'])[0])
            data = data[offset:offset + limit]
        route.fulfill(json=data)


class OptimizationAPI(AuditAPI):
    def __init__(self):
        super().__init__()
        self.report_ready = True
        self.guest_failed = True
        self.profile_failed = False
        self.extra_today = False
        self.settings = [dict(id="setting-general", key="site_name", value="合成站点", description="站点名称", is_sensitive=False, category="general", value_type="string", options=None), dict(id="setting-auth", key="signup_notice", value="合成提示", description="注册提示", is_sensitive=False, category="auth", value_type="string", options=None)]
        self.users = [dict(USER, id=f'user-{i}', full_name=f'合成用户 {i}', email=f'user{i}@example.test', role='patient') for i in range(107)]
        self.doctors = [dict(DOCTOR, id=f'doctor-{i}', full_name=f'合成医生 {i}', email=f'doctor{i}@example.test', is_verified=i % 2 == 0, status='active') for i in range(107)]

    def route(self, route):
        path = urlparse(route.request.url).path.rstrip('/')
        query = parse_qs(urlparse(route.request.url).query)
        if path == self.failed:
            route.fulfill(status=503, json={'detail': '合成网络失败'})
        elif path.endswith('/auth/guest'):
            route.fulfill(status=503 if self.guest_failed else 200, json={'detail': '合成连接失败'} if self.guest_failed else {'session_token': token('guest-1'), 'max_messages': 999, 'message_count': 0})
        elif path.endswith('/patient/profile') and route.request.method != 'GET':
            if self.profile_failed:
                route.fulfill(status=503, json={'detail': '合成保存失败'})
            else:
                self.health.profile.update(route.request.post_data_json)
                route.fulfill(json=self.health.profile)
        elif path.endswith('/patient/care-plans') and self.extra_today:
            route.fulfill(json={'items': [dict(id='plan-many', title='合成多任务计划', revision=1, status='active', effective_status='active', can_execute=True, source_type='patient_reported', start_date=TODAY, end_date=TODAY, progress_percent=0, tasks=[dict(id=f'task-{i}', description=f'合成当天任务 {i}', due_date=TODAY, status='pending', type='self_check') for i in range(6)])], 'next_cursor': None})
        elif path.endswith('/admin/settings'):
            route.fulfill(json=self.settings)
        elif path.endswith('/demo/status'):
            route.fulfill(json={'enabled': not self.report_ready, 'limit': 10, 'used': 0, 'remaining': 10, 'report_center_ready': self.report_ready})
        elif path.endswith('/admin/users') or path.endswith('/admin/doctors'):
            self.calls.append({'method': route.request.method, 'path': path, 'query': query})
            data = self.doctors if path.endswith('/doctors') else self.users
            if query.get('search'):
                data = [r for r in data if query['search'][0] in r['full_name'] or query['search'][0] in r['email']]
            if query.get('is_verified'):
                data = [r for r in data if r['is_verified'] == (query['is_verified'][0] == 'true')]
            if query.get('status'):
                data = [r for r in data if r['status'] == query['status'][0]]
            offset = int(query.get('skip', ['0'])[0])
            limit = int(query.get('limit', ['20'])[0])
            route.fulfill(json=data[offset:offset + limit])
        else:
            super().route(route)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
        api = OptimizationAPI()
        context.route('**/api/v1/**', api.route)
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE + '/login')
        page.get_by_role('button', name='以访客身份体验', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('暂时无法开始访客问诊')
        expect(page).to_have_url(BASE + '/login')
        api.guest_failed = False
        page.get_by_role('button', name='以访客身份体验', exact=True).click()
        expect(page.get_by_role('button', name='新建会话', exact=True).last).to_be_enabled()
        page.evaluate('jwt => {localStorage.setItem("access_token",jwt);localStorage.setItem("user_role","admin")}', token('optimization-user'))
        api.role = 'admin'
        page.goto(BASE + '/admin/users')
        expect(page.get_by_text('本页 20 位用户', exact=True)).to_be_visible()
        for index in range(1, 6):
            page.get_by_role('button', name='下一页', exact=True).click()
            expect(page.get_by_text(f'合成用户 {index * 20}', exact=True)).to_be_visible()
        expect(page.get_by_text('合成用户 106', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='下一页', exact=True)).to_be_disabled()
        page.get_by_placeholder('搜索邮箱或姓名...').fill('合成用户 106')
        expect(page.get_by_text('本页 1 位用户', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='上一页', exact=True)).to_be_disabled()
        page.goto(BASE + '/admin/doctors')
        expect(page.get_by_text('本页 20 位医生', exact=True)).to_be_visible()
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_text('合成医生 20', exact=True)).to_be_visible()
        page.get_by_role('tab', name='已认证', exact=True).click()
        expect(page.get_by_text('合成医生 0', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='上一页', exact=True)).to_be_disabled()
        page.goto(BASE + '/admin/knowledge')
        page.get_by_role('combobox', name='审核状态', exact=True).click()
        with page.expect_response(lambda response: '/admin/knowledge?' in response.url and 'status=pending' in response.url):
            page.get_by_role('option', name='待审核', exact=True).click()
        page.wait_for_load_state('networkidle')
        assert any(c['path'].endswith('/admin/knowledge') and c['query'].get('status') == ['pending'] for c in api.calls)
        page.goto(BASE + '/admin/audit-logs')
        with page.expect_response(lambda response: '/admin/audit-logs?' in response.url and 'user_id=user-106' in response.url):
            page.get_by_role('textbox', name='操作人 ID', exact=True).fill('user-106')
        page.wait_for_load_state('networkidle')
        assert any(c['path'].endswith('/admin/audit-logs') and c['query'].get('user_id') == ['user-106'] for c in api.calls)
        page.goto(BASE + '/admin/email')
        page.get_by_role('tab', name='发送历史', exact=True).click()
        page.get_by_role('textbox', name='收件人或主题', exact=True).fill('example.test')
        page.get_by_role('combobox', name='发送状态', exact=True).click()
        with page.expect_response(lambda response: '/admin/email/logs?' in response.url and 'status=failed' in response.url):
            page.get_by_role('option', name='失败', exact=True).click()
        page.wait_for_load_state('networkidle')
        assert any(c['path'].endswith('/admin/email/logs') and c['query'].get('status') == ['failed'] and c['query'].get('search') == ['example.test'] for c in api.calls)
        api.failed = '/api/v1/admin/email/logs'
        page.get_by_role('button', name='重新加载', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('合成网络失败')
        page.wait_for_timeout(5500)
        expect(page.get_by_role('alert')).to_contain_text('合成网络失败')
        api.failed = ''
        page.get_by_role('button', name='重新加载', exact=True).click()
        expect(page.get_by_role('alert')).to_have_count(0)
        for route_path in ['/admin/knowledge', '/admin/reviews', '/admin/audit-logs']:
            page.goto(BASE + route_path)
            expect(page.get_by_role('button', name='下一页', exact=True)).to_be_enabled()
            for index in [2, 3]:
                page.get_by_role('button', name='下一页', exact=True).click()
                expect(page.get_by_text(f'第 {index} 页', exact=False)).to_be_visible()
                expect(page.locator('tbody tr').first.locator('td[colspan]')).to_have_count(0)
            expect(page.get_by_role('button', name='下一页', exact=True)).to_be_disabled()
        page.goto(BASE + '/admin/users')
        expect(page.get_by_text('合成用户 0', exact=True)).to_be_visible()
        api.failed = '/api/v1/admin/users'
        page.get_by_role('button', name='下一页', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('合成网络失败')
        expect(page.get_by_text('合成用户 0', exact=True)).to_have_count(0)
        api.failed = ''
        page.get_by_role('button', name='重新加载', exact=True).click()
        expect(page.get_by_text('合成用户 20', exact=True)).to_be_visible()
        page.goto(BASE + '/admin/notifications')
        expect(page.get_by_role('cell', name='公告', exact=True)).to_be_visible()
        expect(page.get_by_role('cell', name='高', exact=True)).to_be_visible()
        with page.expect_response(lambda response: '/admin/notifications/' in response.url and 'search=' in response.url):
            page.get_by_role('textbox', name='搜索', exact=True).fill('临时筛选')
        with page.expect_response(lambda response: '/admin/notifications/' in response.url and 'page=2' in response.url):
            page.locator('.MuiTablePagination-actions button').last.click()
        with page.expect_response(lambda response: '/admin/notifications/' in response.url and 'search=' not in response.url):
            page.get_by_role('button', name='重置筛选', exact=True).click()
        calls = [c for c in api.calls if c['path'].endswith('/admin/notifications')]
        assert calls[-1]['query']['page'] == ['1'], calls
        page.goto(BASE + '/admin/settings')
        expect(page.get_by_text('站点名称', exact=True)).to_be_visible()
        page.get_by_role('textbox').first.fill('保留的合成草稿')
        page.get_by_role('tab', name='注册认证').click()
        expect(page.get_by_text('注册提示', exact=True)).to_be_visible()
        page.get_by_role('tab', name='通用').click()
        expect(page.get_by_role('textbox').first).to_have_value('保留的合成草稿')
        screenshots = Path(os.getenv('UI_SCREENSHOT_DIR', str(Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-08-ui-optimization/screenshots')))
        screenshots.mkdir(parents=True, exist_ok=True)
        for width in [320, 390, 768]:
            page.set_viewport_size({'width': width, 'height': 844})
            for path in ['/admin/users', '/admin/doctors', '/admin/providers']:
                page.goto(BASE + path)
                expect(page.locator('tbody tr').first.get_by_role('button').first).to_be_visible()
                action = page.locator('tbody tr').first.locator('td').last
                box = action.bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (path, width, box)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (path, width)
                if path.endswith('providers'):
                    expect(page.get_by_role('button', name='测试连接：合成模型服务', exact=True)).to_be_visible()
                page.screenshot(path=str(screenshots / (path.rsplit('/', 1)[1] + f'-{width}.png')))
        api.role = 'patient'
        page.evaluate('() => localStorage.setItem("user_role","patient")')
        for ready in [True, False]:
            api.report_ready = ready
            page.goto(BASE + '/health')
            link = page.get_by_role('link', name='检查报告 →' if ready else '病例附件 →', exact=True)
            expect(link).to_have_attribute('href', '/reports' if ready else '/cases')
            page.goto(BASE + '/followups')
            expect(page.get_by_role('link', name='整理检查报告' if ready else '查看病例附件', exact=True)).to_have_attribute('href', '/reports' if ready else '/cases')
        api.report_ready = True
        for width in [320, 390, 768, 1440]:
            page.set_viewport_size({'width': width, 'height': 844})
            page.goto(BASE + '/health')
            expect(page.get_by_role('heading', name='正在服用（1 项）', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='已停用（1 项）', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(screenshots / f'health-{width}.png'))
            page.get_by_role('heading', name='正在服用（1 项）', exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(screenshots / f'medications-{width}.png'))
            page.goto(BASE + '/followups')
            expect(page.get_by_text('未来 7 天安排', exact=True)).to_be_visible()
            stats = [page.get_by_text(label, exact=True).bounding_box() for label in ['进行中的计划', '任务已完成', '下一次随访']]
            assert abs(stats[0]['y'] - stats[1]['y']) < 2 and abs(stats[1]['y'] - stats[2]['y']) < 2
            page.screenshot(path=str(screenshots / f'followups-{width}.png'))
        page.goto(BASE + '/health')
        page.get_by_role('button', name='编辑档案', exact=True).click()
        page.get_by_role('button', name='添加疾病', exact=True).click()
        page.get_by_role('button', name='保存', exact=True).click()
        expect(page.get_by_role('textbox', name='疾病名称', exact=True).last).to_be_focused()
        expect(page.get_by_text('请填写疾病名称，或删除这一条', exact=True)).to_be_visible()
        page.get_by_role('textbox', name='疾病名称', exact=True).last.fill('合成新增记录')
        api.profile_failed = True
        page.get_by_role('button', name='保存', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('保存失败')
        expect(page.get_by_role('textbox', name='疾病名称', exact=True).last).to_have_value('合成新增记录')
        api.profile_failed = False
        page.get_by_role('button', name='保存', exact=True).click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        expect(page.get_by_text('合成新增记录', exact=True).last).to_be_visible()
        api.extra_today = True
        page.goto(BASE + '/today')
        more = page.get_by_role('button', name='查看其余 4 项', exact=True)
        expect(more).to_be_visible()
        expect(page.get_by_text('合成当天任务 5', exact=True)).to_have_count(0)
        more.click()
        expect(page.get_by_text('合成当天任务 5', exact=True)).to_be_visible()
        page.get_by_role('button', name='收起当天安排', exact=True).click()
        expect(page.get_by_text('合成当天任务 5', exact=True)).to_have_count(0)
        api.extra_today = False
        api.health.empty = True
        page.goto(BASE + '/reminders')
        expect(page.get_by_role('link', name='查看用药清单', exact=True)).to_have_attribute('href', '/health')
        api.health.empty = False
        api.failed = '/api/v1/auth/me'
        page.goto(BASE + '/chat')
        expect(page.get_by_role('alert')).to_contain_text('无法加载会话')
        api.failed = ''
        page.get_by_role('button', name='重新加载', exact=True).click()
        expect(page.get_by_role('button', name='新建会话', exact=True).last).to_be_enabled()
        chat = page.get_by_placeholder('描述您的症状，或补充检查报告…')
        chat.fill('未发送的合成症状')
        page.locator('input[type=file]').set_input_files({'name': 'synthetic-large.txt', 'mimeType': 'text/plain', 'buffer': b'x' * (10 * 1024 * 1024 + 1)})
        expect(page.get_by_role('alert')).to_contain_text('文件太大')
        expect(chat).to_have_value('未发送的合成症状')
        assert not errors, errors
        browser.close()
    print('PASS: 107条记录、数组末页、筛选回首页、失败重试、报告条件入口、320/390/768/1440布局、档案字段定位与草稿保留、今日安排展开；全部模拟API。')


if __name__ == '__main__':
    main()
