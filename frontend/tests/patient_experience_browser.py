"""患者端体验回归：mock API，只使用合成浏览器数据，不接触实际病例。"""
import json
import os
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, REPORT, history, token


def main():
    REPORT.update({
        'primary_diagnosis': 'IBS-D（ICD-11: DD91.0）',
        'key_findings': ['合成主诉。患者ID：95bb18ce-6d49-4d2a-8059-52e958688fcd',
                         '未检索到资料（retrieved_chunks=0，internal_sources=0，external_sources=0）。体温 38.5°C。'],
        'recommended_actions': ['合成演示：与医生讨论本次情况'],
    })
    now = '2026-09-26T00:00:00Z'
    sessions = [{
        'id': sid, 'title': title, 'created_at': now, 'updated_at': now, 'message_count': 1,
        'messages': [{'id': f'{sid}-m', 'role': 'agent', 'content': '内部诊断摘要', 'structured': REPORT, 'timestamp': now}],
        'chatMode': 'diagnosed', 'reportData': REPORT, 'reportCaseId': 'demo-case-a',
        'backendSessionId': 'server-a', 'pendingSession': None, 'answeredIds': [],
    } for sid, title in [('chat-a', '待删除的合成聊天'), ('chat-b', '需要保留的合成聊天')]]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 950})
            api = MockAPI()
            context.route('**/api/v1/**', api.route)
            page = context.new_page()
            errors, methods = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: methods.append(request.method))
            page.goto(BASE)
            page.evaluate('''([jwt, history]) => {
              localStorage.setItem('access_token', jwt);
              localStorage.setItem('user_role', 'patient');
              localStorage.setItem('medaxis.chat-history.v1:user:ux-test', JSON.stringify(history));
            }''', [token('ux-test'), {'version': 1, 'currentSessionId': 'chat-a', 'sessions': sessions}])
            page.goto(f'{BASE}/chat')
            expect(page.get_by_text('腹泻型肠易激综合征', exact=True)).to_be_visible()
            text = page.locator('body').inner_text()
            for internal in ['DD91.0', '95bb18ce', 'retrieved_chunks', 'internal_sources', 'external_sources', '内部诊断摘要']:
                assert internal not in text, internal
            assert '38.5°C' in text and '未检索到资料' in text

            page.get_by_role('button', name='会话操作：待删除的合成聊天', exact=True).click()
            page.get_by_role('menuitem', name='删除聊天').click()
            dialog = page.get_by_role('dialog', name='删除这段聊天？')
            expect(dialog).to_contain_text('已保存的问诊报告和资料仍会保留')
            dialog.get_by_role('button', name='取消').click()
            assert len(history(page, 'user:ux-test')['sessions']) == 2

            # 存储失败不得让聊天消失或显示删除成功。
            page.evaluate('''() => {
              window.originalSetItem = Storage.prototype.setItem;
              Storage.prototype.setItem = function(key, value) {
                if (key.startsWith('medaxis.chat-history')) throw new Error('synthetic quota failure');
                window.originalSetItem.call(this, key, value);
              };
            }''')
            page.get_by_role('button', name='会话操作：待删除的合成聊天', exact=True).click()
            page.get_by_role('menuitem', name='删除聊天').click()
            page.get_by_role('dialog').get_by_role('button', name='删除聊天', exact=True).click()
            expect(page.get_by_text('聊天未删除，请检查浏览器存储权限后重试。', exact=True)).to_be_visible()
            assert history(page, 'user:ux-test')['currentSessionId'] == 'chat-a'
            page.evaluate('() => { Storage.prototype.setItem = window.originalSetItem; }')

            page.get_by_role('button', name='会话操作：待删除的合成聊天', exact=True).click()
            page.get_by_role('menuitem', name='删除聊天').click()
            page.get_by_role('dialog').get_by_role('button', name='删除聊天', exact=True).click()
            expect(page.get_by_role('button', name='会话操作：待删除的合成聊天')).to_have_count(0)
            page.reload()
            expect(page.get_by_role('button', name='会话操作：需要保留的合成聊天', exact=True)).to_be_visible()
            assert all(item['id'] != 'chat-a' for item in history(page, 'user:ux-test')['sessions'])
            assert 'DELETE' not in methods
            print('PASS: 取消、存储失败和刷新后的聊天删除；没有调用服务端删除接口')

            page.get_by_role('button', name='问诊记录', exact=True).click()
            expect(page).to_have_url(f'{BASE}/cases')
            expect(page.get_by_role('heading', name='问诊记录', exact=True)).to_be_visible()
            expect(page.get_by_text('腹泻型肠易激综合征', exact=True)).to_be_visible()
            expect(page.get_by_text('测试危险信号', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='整理就诊摘要', exact=True)).not_to_be_visible()
            expect(page.get_by_label('就诊时间', exact=True)).not_to_be_visible()
            page.get_by_role('button', name='准备去就诊', exact=True).click()
            expect(page.get_by_role('button', name='整理就诊摘要', exact=True)).to_be_visible()
            page.get_by_role('button', name='记录就诊结果', exact=True).click()
            expect(page.get_by_label('就诊时间', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='整理就诊摘要', exact=True)).not_to_be_visible()
            artifact = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-09-26-patient-ux'
            artifact.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(artifact / 'records-desktop.png'), full_page=True)
            page.get_by_role('button', name='病例 B · 失败切换', exact=False).click()
            expect(page.get_by_role('alert')).to_contain_text('这条问诊记录暂时无法读取')
            expect(page.get_by_text('腹泻型肠易激综合征', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='记录就诊结果', exact=True)).to_have_count(0)
            page.get_by_role('button', name='AI 问诊', exact=True).click()
            expect(page).to_have_url(f'{BASE}/chat')
            expect(page.get_by_role('button', name='会话操作：需要保留的合成聊天', exact=True)).to_be_visible()
            print('PASS: 删除聊天后报告仍可查看；阶段切换、失败切换及返回问诊')

            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(f'{BASE}/cases?case_id=demo-case-a')
            expect(page.get_by_text('腹泻型肠易激综合征', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(artifact / 'records-mobile.png'), full_page=True)
            assert not errors, errors
            print('PASS: 手机宽度无横向溢出；页面没有运行时异常')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
