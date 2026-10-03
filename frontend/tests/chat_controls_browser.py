"""问诊控件回归：合成 API/SSE，检查对齐、发送与新建入口。"""
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, token
from consultation_sidebar_browser import SidebarAPI

ARTIFACTS = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-chat-controls-polish'
PLACEHOLDER = '描述您的症状，或补充检查报告…'


def assert_alignment(page):
    composer = page.get_by_role('group', name='问诊输入栏')
    field = page.get_by_placeholder(PLACEHOLDER)
    button = composer.get_by_role('button', name='发送消息', exact=True)
    face = button.locator('.send-face')
    expect(face).to_have_css('width', '32px')
    expect(face).to_have_css('height', '32px')
    expect(button).to_have_css('width', '44px')
    expect(button).to_have_css('height', '44px')
    field_box = field.bounding_box()
    middle = field_box['y'] + field_box['height'] / 2
    for label in ['添加文件', '添加图片', '语音输入', '发送消息']:
        control = composer.get_by_role('button', name=label, exact=True)
        if control.is_visible():
            box = control.bounding_box()
            assert abs(box['y'] + box['height'] / 2 - middle) <= 1, (label, box, field_box)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            context.route('**/api/v1/**', SidebarAPI().route)
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            page = context.new_page()
            errors, submitted = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def capture(request):
                if urlparse(request.url).path.endswith('/route/stream'):
                    assert request.method == 'POST'
                    submitted.append(request.post_data_json['message'])

            page.on('request', capture)
            page.goto(BASE)
            page.evaluate('jwt => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('controls-user'))
            page.goto(BASE + '/chat')
            field = page.get_by_placeholder(PLACEHOLDER)
            expect(field).to_be_visible()
            new_session = page.get_by_role('button', name='新建会话', exact=True)
            expect(new_session).to_have_css('background-color', 'rgb(15, 118, 110)')
            expect(new_session.locator('svg')).to_be_visible()
            expect(new_session).to_have_css('color', 'rgb(255, 255, 255)')
            send_button = page.get_by_role('button', name='发送消息', exact=True)
            expect(send_button).to_be_disabled()
            assert_alignment(page)
            page.mouse.move(0, 0)
            page.get_by_role('group', name='问诊输入栏').screenshot(path=str(ARTIFACTS / 'composer-single-line.png'))
            field.fill('   ')
            expect(send_button).to_be_disabled()
            field.fill('合成第一行')
            field.press('Shift+Enter')
            expect(field).to_have_value('合成第一行\n')
            assert not submitted
            field.fill('合成第一行\n合成第二行\n合成第三行')
            expect(send_button).to_be_enabled()
            assert_alignment(page)
            page.mouse.move(0, 0)
            page.screenshot(path=str(ARTIFACTS / 'chat-desktop.png'))
            page.get_by_role('group', name='问诊输入栏').screenshot(path=str(ARTIFACTS / 'composer-desktop.png'))
            field.fill('  合成按钮发送  ')
            send_button.click()
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            expect(new_session).to_be_enabled()
            assert submitted == ['合成按钮发送']
            new_session.click()
            expect(field).to_have_value('')
            field.fill('合成 Enter 发送')
            field.press('Enter')
            expect(page.get_by_text('持续多久？', exact=True)).to_be_visible()
            expect(new_session).to_be_enabled()
            assert submitted == ['合成按钮发送', '合成 Enter 发送']
            new_session.click()
            expect(field).to_have_value('')
            print('PASS: 新建按钮可见、发送视觉 32px/点击区 44px、单行/多行垂直对齐、空白禁用、Shift+Enter 换行、按钮及 Enter 发送')

            for width in [390, 320, 768]:
                page.set_viewport_size({'width': width, 'height': 844})
                expect(new_session).to_be_visible()
                expect(new_session.locator('svg')).to_be_visible()
                summary = page.get_by_role('button', name='问诊摘要', exact=True)
                expect(summary).to_be_visible()
                new_box, summary_box = new_session.bounding_box(), summary.bounding_box()
                assert new_box['x'] + new_box['width'] <= summary_box['x']
                assert summary_box['x'] + summary_box['width'] <= width
                assert_alignment(page)
                field.fill('合成一行\n合成两行\n合成三行')
                assert_alignment(page)
                nav_box = page.get_by_role('navigation', name='移动端导航').bounding_box()
                composer_box = page.get_by_role('group', name='问诊输入栏').bounding_box()
                assert composer_box['y'] + composer_box['height'] <= nav_box['y']
                if width == 390:
                    page.mouse.move(0, 0)
                    page.screenshot(path=str(ARTIFACTS / 'chat-mobile.png'))
                field.fill('')
            assert not errors, errors
            print('PASS: 320/390/768px 加号与按钮清晰、控件不重叠、输入/图标对齐、底部导航无遮挡，无运行时异常')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
