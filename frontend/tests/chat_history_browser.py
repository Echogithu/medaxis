"""Browser regression with mocked API/SSE; no LLM or database writes.

Start Vite on 127.0.0.1:3001, then run with Python + Playwright installed:
  python tests/chat_history_browser.py
Uses installed Edge by default (PLAYWRIGHT_CHANNEL can override it).
"""
import base64
import json
import os
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('CHAT_TEST_URL', 'http://127.0.0.1:3001')
REPORT = {
    'primary_diagnosis': '测试报告，仅用于回归验证', 'icd11_code': 'TEST',
    'confidence': 'low', 'referral_needed': False, 'red_flags': ['测试危险信号'],
}


def token(subject, revision=1):
    payload = base64.urlsafe_b64encode(json.dumps({'sub': subject, 'exp': revision}).encode()).decode().rstrip('=')
    return f'header.{payload}.signature'


def events(*items):
    return ''.join(f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n' for name, data in items)


class MockAPI:
    def __init__(self):
        self.requests = []
        self.created_guests = 0
        self.parse_complete = False

    def route(self, route):
        request = route.request
        url = urlparse(request.url)
        query = parse_qs(url.query)
        path = unquote(url.path)
        self.requests.append((path, query, request.headers, request.post_data))
        data = {}
        if path.endswith('/demo/status'):
            data = {'enabled': False, 'limit': 0, 'used': 0, 'remaining': 0, 'report_center_ready': True}
        elif path.endswith('/auth/me'):
            jwt = request.headers['authorization'].split()[1]
            sub = json.loads(base64.urlsafe_b64decode(jwt.split('.')[1] + '=='))['sub']
            data = {'id': sub, 'role': 'patient'}
        elif path.endswith('/auth/guest'):
            self.created_guests += 1
            data = {'session_token': token('guest-1'), 'max_messages': 999, 'message_count': 0}
        elif path.endswith('/auth/guest/status'):
            data = {'interaction_count': 0, 'max_interactions': 999, 'remaining': 999, 'can_interact': True}
        elif path.endswith('/route/stream'):
            label = query['message'][0]
            body = events(
                ('text', {'text': f'已记录：{label}'}),
                ('question', {
                    'question_id': 'q1',
                    'questions': [
                        {'question_id': 'q1', 'question': '持续多久？', 'type': 'choice', 'options': ['一天', '两天']},
                        {'question_id': 'q2', 'question': '程度如何？', 'type': 'choice', 'options': ['轻微', '严重']},
                    ],
                }),
                ('complete', {'status': 'waiting_for_answer', 'session_id': f'backend-{label}'}),
            )
            route.fulfill(status=200, content_type='text/event-stream', body=body)
            return
        elif path.endswith('/route/stream/continue'):
            if query['question_id'][0] == 'q1':
                body = events(('text', {'text': '第一项回答已记录'}),
                              ('complete', {'status': 'waiting_for_answer', 'session_id': query['session_id'][0]}))
            else:
                body = events(('text', {'text': '已完成问诊'}), ('structured', REPORT),
                              ('complete', {'status': 'completed', 'session_id': query['session_id'][0], 'case_id': 'demo-case-a'}))
            route.fulfill(status=200, content_type='text/event-stream', body=body)
            return
        elif path.endswith('/chat'):
            body = events(('text', {'text': '历史上下文续聊成功'}), ('complete', {'session_id': 'child-conversation'}))
            route.fulfill(status=200, content_type='text/event-stream', body=body)
            return
        elif path.endswith('/documents/upload'):
            data = {'file_id': 'file-1', 'filename': 'report.txt', 'status': 'processing', 'parse_method': 'file-extract'}
        elif path.endswith('/documents/file-1/result'):
            data = {'file_id': 'file-1', 'status': 'completed' if self.parse_complete else 'processing'}
            if self.parse_complete:
                data['result'] = {'file_id': 'file-1', 'indicators': [], 'overall_confidence': 0.9,
                                  'requires_manual_review': False, 'raw_response': '', 'error': ''}
        elif path.endswith('/patient/cases'):
            data = [
                {'id': 'demo-case-a', 'title': '病例 A · 演示报告', 'status': 'pending_review', 'created_at': '2026-09-26T00:00:00Z'},
                {'id': 'demo-case-b', 'title': '病例 B · 失败切换', 'status': 'pending_review', 'created_at': '2026-09-25T00:00:00Z'},
            ]
        elif path.startswith('/api/v1/patient/cases/') and path.endswith('/reports'):
            # 总结页同时读取关联报告；空列表也需要符合分页接口契约。
            data = {'items': [], 'total': 0, 'page': 1, 'limit': 10}
        elif path.endswith('/patient/cases/demo-case-a/recovery'):
            data = {
                'case': {'id': 'demo-case-a', 'title': '病例 A · 演示报告', 'status': 'pending_review', 'created_at': '2026-09-26T00:00:00Z'},
                'report': REPORT, 'lab_reports': [], 'materials': [],
            }
        elif path.endswith('/patient/cases/demo-case-b/recovery'):
            route.fulfill(status=500, content_type='application/json', body='{"detail":"synthetic recovery failure"}')
            return
        elif path.endswith('/preparation') and request.method == 'POST':
            route.fulfill(status=500, content_type='application/json', body='{"detail":{"message":"合成准备保存失败"}}')
            return
        elif path.endswith('/preparation'):
            data = {'package': None, 'history': []}
        elif path.endswith('/post-visit-feedback'):
            data = {'feedback': None, 'history': []}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))


def history(page, owner):
    return page.evaluate('(key) => JSON.parse(localStorage.getItem(key))', f'medaxis.chat-history.v1:{owner}')


def send(page, text):
    field = page.get_by_placeholder('描述您的症状，或补充检查报告…')
    field.fill(text)
    field.press('Enter')


def ready(page):
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('button', name='新建会话', exact=True).last).to_be_enabled()


def reload(page):
    page.reload(wait_until='domcontentloaded', timeout=15_000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            api = MockAPI()
            context = browser.new_context(viewport={'width': 1280, 'height': 960})
            context.route('**/api/v1/**', api.route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('([access, guest]) => { localStorage.setItem("access_token", access); localStorage.setItem("user_role", "patient"); localStorage.setItem("guest_token", guest); }',
                          [token('user-a'), token('old-guest')])
            page.goto(f'{BASE}/chat')
            ready(page)
            send(page, '历史会话A')
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            ready(page)
            reload(page)
            ready(page)
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            assert history(page, 'user:user-a')['sessions'][0]['pendingSession']['sessionId'] == 'backend-历史会话A'
            page.get_by_role('button', name='一天', exact=True).click()
            expect(page.get_by_role('button', name='轻微', exact=True)).to_be_enabled()
            expect(page.get_by_role('button', name='新建会话', exact=True).last).to_be_enabled()
            page.get_by_role('button', name='轻微', exact=True).click()
            page.wait_for_function('Object.values(localStorage).some(v => v.includes("测试报告，仅用于回归验证"))')
            expect(page.get_by_role('button', name='查看问诊记录', exact=True)).to_be_visible()
            page.get_by_role('button', name='查看问诊记录', exact=True).click()
            assert page.url.endswith('/cases?case_id=demo-case-a'), page.url
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(page.get_by_text('测试危险信号', exact=True)).to_be_visible()
            expect(page.get_by_text('全科/普通门诊', exact=True)).not_to_be_visible()
            page.get_by_role('button', name='准备去就诊', exact=True).click()
            page.get_by_role('button', name='整理就诊摘要', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='合成准备保存失败')).to_be_visible()
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True).last).to_be_visible()
            page.get_by_role('button', name='病例 B · 失败切换', exact=False).click()
            expect(page.get_by_role('alert')).to_contain_text('这条问诊记录暂时无法读取')
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_have_count(0)
            print('PASS: report opens its saved case; risk flags stay visible and failed case switches clear stale data')
            page.goto(f'{BASE}/chat')
            reload(page)  # also closes the full-screen report
            ready(page)
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_be_visible()
            send(page, '继续咨询')
            expect(page.get_by_text('历史上下文续聊成功', exact=True)).to_be_visible()
            ready(page)
            chat_requests = [item for item in api.requests if item[0].endswith('/chat')]
            assert chat_requests[-1][0] == '/api/v1/agents/sessions/backend-历史会话A/chat'
            assert chat_requests[-1][2]['authorization'] == f'Bearer {token("user-a")}'
            assert 'x-guest-token' not in chat_requests[-1][2]
            first_stream = next(item for item in api.requests if item[0].endswith('/route/stream'))
            assert first_stream[1]['token'] == [token('user-a')]
            assert 'guest_token' not in first_stream[1]
            continued = [item for item in api.requests if item[0].endswith('/continue')]
            assert [item[1]['question_id'][0] for item in continued[:2]] == ['q1', 'q2']
            assert all(item[1]['session_id'] == ['backend-历史会话A'] for item in continued[:2])
            assert [json.loads(item[3])['answer'] for item in continued[:2]] == ['一天', '轻微']
            print('PASS: multiple interview cards stay clickable and answers are submitted in order')
            print('PASS: reload restores interview, report, timestamps and post-diagnosis continuation')

            page.get_by_role('button', name='新建会话', exact=True).last.click()
            send(page, '历史会话B')
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            ready(page)
            page.get_by_role('button', name='历史会话A', exact=True).click()
            expect(page.get_by_text('历史上下文续聊成功', exact=True)).to_be_visible()
            expect(page.get_by_text('已记录：历史会话B', exact=True)).to_have_count(0)
            reload(page)
            ready(page)
            assert len(history(page, 'user:user-a')['sessions']) == 2
            expect(page.get_by_text('历史上下文续聊成功', exact=True)).to_be_visible()
            page.get_by_role('button', name='历史会话B', exact=True).click()
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            print('PASS: multiple sessions switch independently; selection survives reload without duplicates')

            page.evaluate('(jwt) => localStorage.setItem("access_token", jwt)', token('user-b'))
            reload(page)
            ready(page)
            expect(page.get_by_role('button', name='历史会话A', exact=True)).to_have_count(0)
            page.evaluate('(jwt) => localStorage.setItem("access_token", jwt)', token('user-a', 2))
            reload(page)
            ready(page)
            expect(page.get_by_role('button', name='历史会话A', exact=True)).to_be_visible()
            page.evaluate('localStorage.setItem("medaxis.chat-history.v1:user:user-a", "{broken")')
            reload(page)
            expect(page.get_by_role('alert')).to_contain_text('原记录未被覆盖')
            assert page.evaluate('localStorage.getItem("medaxis.chat-history.v1:user:user-a")') == '{broken'
            assert not errors, errors
            context.close()
            print('PASS: account isolation, token renewal and corrupt-storage protection')

            guest_api = MockAPI()
            guest_context = browser.new_context(viewport={'width': 1280, 'height': 960})
            guest_context.route('**/api/v1/**', guest_api.route)
            page = guest_context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'{BASE}/chat')
            ready(page)
            send(page, '访客会话')
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            ready(page)
            reload(page)
            ready(page)
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            assert guest_api.created_guests == 1
            assert page.evaluate('localStorage.getItem("guest_token")') == token('guest-1')
            page.get_by_role('button', name='新建会话', exact=True).last.click()
            page.locator('input[type=file]').set_input_files({'name': 'report.txt', 'mimeType': 'text/plain', 'buffer': b'test report'})
            page.wait_for_function('Object.values(localStorage).some(v => v.includes("uploadFileId"))')
            guest_api.parse_complete = True
            reload(page)
            ready(page)
            expect(page.get_by_text('report.txt', exact=True).first).to_be_visible()
            records = history(page, 'guest:guest-1')
            upload_session = next(item for item in records['sessions'] if item['id'] == records['currentSessionId'])
            upload = next(item for item in upload_session['messages'] if item.get('uploadFileId'))
            assert upload['uploadStatus'] == 'completed'
            assert any(item[0].endswith('/lab-reports') for item in guest_api.requests)
            assert guest_api.created_guests == 1
            assert not errors, errors
            guest_context.close()
            print('PASS: stable guest identity and upload polling resumes after reload')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
