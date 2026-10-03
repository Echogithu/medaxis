"""注册表单回归：合成接口验证角色字段、提交、错误恢复与响应式。"""
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE

ARTIFACTS = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-registration-polish'


def choose(page, label, value):
    page.get_by_role('combobox', name=label, exact=True).click()
    page.get_by_role('option', name=value, exact=True).click()


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    submitted, documents, errors = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('**/data/pca.json', lambda route: route.fulfill(json={'广东省': {'深圳市': ['南山区']}, '浙江省': {'杭州市': ['西湖区']}}))

            def route_api(route):
                path = urlparse(route.request.url).path
                if path == '/api/v1/auth/register':
                    submitted.append(route.request.post_data_json)
                    if len(submitted) == 1:
                        route.fulfill(status=409, json={'detail': '合成邮箱已被注册'})
                    else:
                        route.fulfill(json={'message': '注册成功，请验证邮箱'})
                elif path == '/api/v1/auth/register/doctor':
                    submitted.append(route.request.post_data)
                    route.fulfill(json={'message': '注册成功，请等待管理员审核'})
                else:
                    route.fulfill(status=404, json={'detail': '未配置的合成接口'})

            context.route('**/api/v1/**', route_api)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            page.goto(BASE + '/register')
            expect(page.get_by_role('heading', name='创建账户', exact=True)).to_be_visible()
            expect(page.get_by_role('combobox', name='学历')).to_have_count(0)
            expect(page.get_by_role('region', name='执业信息')).to_have_count(0)
            page.screenshot(path=str(ARTIFACTS / 'register-empty-desktop.png'), full_page=True)
            nickname = page.get_by_role('textbox', name='昵称')
            email = page.get_by_role('textbox', name='邮箱地址')
            page.get_by_role('button', name='立即注册', exact=True).click()
            expect(page.get_by_text('请输入昵称', exact=True)).to_be_visible()
            expect(page.get_by_text('请输入邮箱地址', exact=True)).to_be_visible()
            nickname.fill('合成用户')
            email.fill('invalid-email')
            page.get_by_placeholder('至少 8 位字符', exact=True).fill('short')
            page.get_by_placeholder('请再次输入密码', exact=True).fill('different')
            page.get_by_role('spinbutton', name='年龄（岁）').fill('121')
            page.get_by_role('spinbutton', name='月龄补充').fill('12')
            page.get_by_role('textbox', name='手机号（选填）').fill('123')
            page.get_by_role('button', name='立即注册', exact=True).click()
            for message in ['请输入有效的邮箱地址', '密码长度至少为 8 个字符', '两次输入的密码不一致', '请输入 0–120 的整数', '请输入 0–11 的整数', '请输入有效的手机号码']:
                expect(page.get_by_text(message, exact=True)).to_be_visible()
            assert not submitted
            page.get_by_role('spinbutton', name='年龄（岁）').fill('0')
            page.get_by_role('spinbutton', name='月龄补充').fill('11')
            page.get_by_role('textbox', name='手机号（选填）').fill('')
            nickname.fill('合成用户')
            email.fill('register@example.test')
            page.get_by_placeholder('至少 8 位字符', exact=True).fill('Synthetic8!')
            page.get_by_placeholder('请再次输入密码', exact=True).fill('Synthetic8!')
            page.get_by_role('button', name='显示密码', exact=True).click()
            expect(page.get_by_placeholder('至少 8 位字符', exact=True)).to_have_attribute('type', 'text')
            page.get_by_role('button', name='隐藏密码', exact=True).click()
            page.get_by_role('button', name='医生', exact=True).click()
            expect(page.get_by_role('textbox', name='真实姓名')).to_have_value('合成用户')
            expect(email).to_have_value('register@example.test')
            choose(page, '学历（选填）', '硕士')
            page.get_by_role('button', name='患者', exact=True).click()
            expect(nickname).to_have_value('合成用户')
            expect(page.get_by_role('combobox', name='学历')).to_have_count(0)
            page.get_by_role('button', name='立即注册', exact=True).click()
            expect(page.get_by_text('请选择省份', exact=True)).to_be_visible()
            expect(page.get_by_text('请同意用户协议和隐私政策', exact=True)).to_be_visible()
            assert not submitted
            choose(page, '省/直辖市', '广东省')
            expect(page.get_by_text('请选择省份', exact=True)).to_have_count(0)
            choose(page, '市', '深圳市')
            choose(page, '区/县', '南山区')
            choose(page, '省/直辖市', '浙江省')
            expect(page.get_by_role('combobox', name='市', exact=True)).not_to_contain_text('深圳市')
            expect(page.get_by_role('combobox', name='区/县')).to_be_disabled()
            page.get_by_role('checkbox', name='同意用户协议和隐私政策').check()
            expect(page.get_by_text('请同意用户协议和隐私政策', exact=True)).to_have_count(0)
            page.get_by_role('button', name='用户协议', exact=True).click()
            expect(page.get_by_role('dialog')).to_contain_text('用户服务协议')
            page.get_by_role('dialog').get_by_role('button', name='我已阅读').click()
            page.get_by_role('button', name='立即注册', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('合成邮箱已被注册')
            expect(nickname).to_have_value('合成用户')
            expect(page.get_by_role('button', name='立即注册', exact=True)).to_be_enabled()
            assert submitted[0]['role'] == 'patient' and 'education' not in submitted[0]
            assert submitted[0]['age_years'] == 0 and submitted[0]['age_months'] == 11
            assert 'hospital' not in submitted[0] and 'license_number' not in submitted[0]
            page.mouse.move(0, 0)
            page.screenshot(path=str(ARTIFACTS / 'register-desktop.png'), full_page=True)
            for width in [320, 390, 768]:
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                for label in ['至少 8 位字符', '请再次输入密码']:
                    box = page.get_by_placeholder(label, exact=True).bounding_box()
                    assert box['width'] >= 60 and box['x'] >= 0 and box['x'] + box['width'] <= width
                if width == 390:
                    page.screenshot(path=str(ARTIFACTS / 'register-mobile.png'), full_page=True)
            page.get_by_role('button', name='立即注册', exact=True).click()
            expect(page).to_have_url(BASE + '/login')
            assert len(documents) == 1, documents
            assert submitted[1]['role'] == 'patient' and 'education' not in submitted[1]
            print('PASS: 患者无学历字段及提交数据；角色切换保留账户资料；省市联动、协议、密码显隐、失败重试、登录路由与 320/390/768px 布局')

            page.goto(BASE + '/register')
            page.get_by_role('button', name='医生', exact=True).click()
            page.get_by_role('textbox', name='真实姓名').fill('合成医生')
            email.fill('doctor@example.test')
            page.get_by_placeholder('至少 8 位字符', exact=True).fill('Synthetic8!')
            page.get_by_placeholder('请再次输入密码', exact=True).fill('Synthetic8!')
            choose(page, '省/直辖市', '广东省')
            page.get_by_role('checkbox', name='同意用户协议和隐私政策').check()
            page.get_by_role('button', name='提交审核', exact=True).click()
            assert len(submitted) == 2
            page.get_by_role('textbox', name='执业医院').fill('合成医院')
            page.get_by_role('textbox', name='科室').fill('合成科室')
            page.get_by_role('textbox', name='执业证号').fill('SYNTHETIC-LICENSE')
            choose(page, '职称', '主治医师')
            choose(page, '学历（选填）', '本科')
            page.locator('#credential-files').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': b'synthetic'})
            expect(page.get_by_role('button', name='已选择 1 个文件')).to_be_visible()
            page.mouse.move(0, 0)
            page.screenshot(path=str(ARTIFACTS / 'register-doctor-mobile.png'), full_page=True)
            page.get_by_role('button', name='提交审核', exact=True).click()
            expect(page).to_have_url(BASE + '/login')
            assert len(submitted) == 3
            assert 'name="education"\r\n\r\n本科' in submitted[2]
            assert 'name="license_number"\r\n\r\nSYNTHETIC-LICENSE' in submitted[2]
            assert 'filename="synthetic.png"' in submitted[2]
            assert not errors, errors
            print('PASS: 医生必填资质校验、学历与证件通过既有 multipart 提交，审核结果跳转；无运行时异常')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
