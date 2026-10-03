"""报告阅读回归：模拟认证/API，合成引用；不调用真实模型或写数据库。

先启动 Vite 127.0.0.1:3001，再运行 python tests/report_reading_browser.py。
截图默认在临时目录；REPORT_SCREENSHOT_DIR 可指定输出目录。
"""
import os
import re
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, REPORT, token

DOCUMENT_ID = '0a9eb4c3-b646-4019-baea-501865135a51'
CHUNK_ID = '1542c3d4-0a61-4ae1-8443-dc0b5b1153fb'
EXCERPT = ('合成原文片段：请结合完整上下文阅读，体温 38.5°C，血压 135/85 mmHg。\n'
           '这段合成文字用于检查原文的换行和完整性，不构成医学建议。\n\n') * 24 + '5\n原文最后一段，不能被省略。'


def seed_report():
    citations = [{
        'citation_id': f'S{index}', 'source_type': 'internal',
        'title': f'合成参考资料 {index}：长标题用于检查患者报告的来源排版',
        'excerpt': EXCERPT if index == 1 else f'第 {index} 条合成原文，仅用于展示回归。',
        'document_id': DOCUMENT_ID, 'chunk_id': f'{CHUNK_ID}-{index}',
        'chunk_index': index - 1, 'document_type': 'platform_guideline',
    } for index in range(1, 5)]
    citations.append({'citation_id': 'S5', 'source_type': 'external', 'title': '合成外部来源',
                      'excerpt': '合成外部片段；不表示临床验证。', 'url': 'https://example.org/reference',
                      'source_engine': 'synthetic', 'is_trusted': False})
    citations.append({'citation_id': 'S9', 'source_type': 'external', 'title': '无效链接',
                      'excerpt': '应被过滤', 'url': 'javascript:alert(1)'})
    REPORT.update({
        'primary_diagnosis': '合成初步参考：用于测试引用导航[S4]',
        'key_findings': [f'第 {i} 项合成发现，数值保留 38.5°C。' for i in range(1, 9)],
        'recommended_actions': ['合成建议：与医生讨论[S1]', '合成建议：记录变化[S5]'],
        'recommended_tests': ['合成检查一', '合成检查二'],
        'follow_up_timeline': '合成时间说明，仅用于回归。',
        'knowledge_citations': citations,
    })
    now = '2026-09-30T00:00:00Z'
    messages = [{'id': f'm-{i}', 'role': 'user' if i % 2 else 'agent',
                 'content': f'第 {i} 轮合成对话。\n' + '用于验证长聊天返回顶部。\n' * 4, 'timestamp': now}
                for i in range(16)]
    messages.append({'id': 'report-message', 'role': 'agent', 'content': '问诊总结已生成',
                     'structured': REPORT, 'timestamp': now})
    session = {'id': 'report-reading', 'title': '合成报告阅读', 'created_at': now,
               'updated_at': now, 'message_count': 8, 'messages': messages,
               'chatMode': 'diagnosed', 'reportData': REPORT, 'reportCaseId': 'demo-case-a',
               'backendSessionId': 'server-reading', 'pendingSession': None, 'answeredIds': []}
    return {'version': 1, 'currentSessionId': session['id'], 'sessions': [session]}


def at_top(page, region):
    page.wait_for_function('el => el.scrollTop < 2', arg=region.element_handle())


def main():
    saved = seed_report()
    artifacts = Path(os.getenv('REPORT_SCREENSHOT_DIR', tempfile.gettempdir()))
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/api/v1/**', MockAPI().route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('''([jwt, saved]) => {
                localStorage.setItem('access_token', jwt);
                localStorage.setItem('user_role', 'patient');
                localStorage.setItem('medaxis.chat-history.v1:user:reading-test', JSON.stringify(saved));
            }''', [token('reading-test'), saved])
            page.goto(f'{BASE}/chat')
            chat = page.locator('[aria-label="问诊消息"]')
            chat.evaluate('el => { el.scrollTop = el.scrollHeight; }')
            page.get_by_role('button', name='回到问诊顶部', exact=True).click()
            at_top(page, chat)
            expect(page.get_by_role('button', name='回到问诊顶部', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='回到最新消息', exact=True)).to_be_visible()
            page.get_by_role('button', name='回到最新消息', exact=True).click()
            page.wait_for_function('el => el.scrollHeight - el.scrollTop - el.clientHeight < 5', arg=chat.element_handle())
            expect(page.get_by_role('button', name='回到问诊顶部', exact=True)).to_be_visible()
            print('PASS: 长聊天向上返回与回到最新消息互不混淆')

            page.get_by_role('button', name='查看问诊总结', exact=True).last.click()
            dialog = page.get_by_role('dialog', name='本次问诊总结')
            body = dialog.get_by_role('region', name='问诊总结正文')
            expect(dialog.locator('xpath=..')).to_have_css('opacity', '1')
            expect(dialog.get_by_role('button', name='回到总结顶部')).to_have_count(0)
            page.screenshot(path=str(artifacts / 'medaxis-report-summary-desktop.png'))
            dialog.get_by_role('link', name='引用 S4，查看来源').click()
            card4 = dialog.get_by_role('article', name='参考资料 S4')
            expect(card4).to_be_visible()
            expect(card4).to_be_focused()
            expect(dialog.get_by_text('5 条来源', exact=True)).to_be_visible()
            expect(dialog.get_by_role('button', name='回到总结顶部')).to_be_visible()
            expect(dialog.get_by_role('article', name='参考资料 S1').get_by_text('[S1] 内部知识库', exact=True)).to_be_visible()
            expect(dialog.get_by_role('article', name='参考资料 S5').get_by_text('[S5] 外部来源', exact=True)).to_be_visible()
            for desktop_width in [1440, 1920, 1024]:
                page.set_viewport_size({'width': desktop_width, 'height': 1000})
                report_box = dialog.get_by_role('article', name='问诊总结报告', exact=True).bounding_box()
                button_box = dialog.get_by_role('button', name='回到总结顶部').bounding_box()
                gap = button_box['x'] - report_box['x'] - report_box['width']
                assert 8 <= gap <= 24, (desktop_width, gap)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            print('PASS: 内部知识库/外部来源标注明确，1024/1440/1920 按钮紧邻报告右侧')
            assert dialog.locator('a[href^="javascript:"]').count() == 0
            dialog.get_by_role('button', name='收起更多来源', exact=True).click()
            expect(card4).not_to_be_visible()
            card1 = dialog.get_by_role('article', name='参考资料 S1')
            expect(card1.get_by_text(DOCUMENT_ID, exact=True)).not_to_be_visible()
            expect(card1.get_by_role('region', name='S1 原文片段')).not_to_be_visible()
            card1.get_by_role('button', name='查看 S1 原文片段').click()
            original = card1.get_by_role('region', name='S1 原文片段')
            expect(original).to_be_visible()
            assert original.text_content() == EXCERPT
            assert original.evaluate('el => el.clientHeight <= 341 && el.scrollHeight > el.clientHeight')
            card1.get_by_text('来源详情', exact=True).click()
            expect(card1.get_by_text(DOCUMENT_ID, exact=True)).to_be_visible()
            card1.get_by_text('来源详情', exact=True).click()
            card1.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / 'medaxis-report-reference-desktop.png'))
            card1.get_by_role('button', name='收起 S1 原文片段').click()
            expect(original).not_to_be_visible()
            dialog.get_by_role('button', name='回到总结顶部').click()
            at_top(page, body)
            expect(body).to_be_focused()
            expect(dialog.get_by_role('button', name='回到总结顶部')).to_have_count(0)
            dialog.get_by_role('button', name='关闭问诊总结').click()
            page.get_by_role('button', name='查看问诊总结', exact=True).last.click()
            expect(dialog.get_by_role('button', name='回到总结顶部')).to_have_count(0)
            expect(dialog.get_by_role('article', name='参考资料 S1')).not_to_be_visible()
            print('PASS: 引用跨折叠导航、默认三条、原文完整且限高、技术详情按需、总结回顶部与重开复位')

            dialog.get_by_role('button', name='关闭问诊总结').click()
            page.emulate_media(reduced_motion='reduce')
            for width in [390, 320]:
                page.set_viewport_size({'width': width, 'height': 844})
                page.get_by_role('button', name='查看问诊总结', exact=True).last.click()
                expect(dialog.locator('xpath=..')).to_have_css('opacity', '1')
                dialog.get_by_role('link', name='引用 S4，查看来源').click()
                expect(card4).to_be_visible()
                expect(card4).to_be_focused()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert body.evaluate('el => el.scrollWidth <= el.clientWidth')
                expect(dialog.get_by_role('article', name='参考资料 S1').get_by_text('[S1] 内部知识库', exact=True)).to_be_visible()
                button_box = dialog.get_by_role('button', name='回到总结顶部').bounding_box()
                assert button_box['x'] >= 0 and button_box['x'] + button_box['width'] <= width
                if width == 390:
                    page.screenshot(path=str(artifacts / 'medaxis-report-reference-mobile.png'))
                dialog.get_by_role('button', name='回到总结顶部').click()
                at_top(page, body)
                dialog.get_by_role('button', name='关闭问诊总结').click()
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(f'{BASE}/cases?case_id=demo-case-a')
            references = page.get_by_role('button', name=re.compile('参考资料与说明'))
            references.click()
            expect(page.get_by_role('article', name='参考资料 S1')).to_be_visible()
            expect(page.get_by_role('article', name='参考资料 S4')).not_to_be_visible()
            assert not errors, errors
            print('PASS: 手机 390/320 无横向溢出、减少动效返回、问诊记录复用新来源样式')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
