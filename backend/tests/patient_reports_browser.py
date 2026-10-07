"""真实 Edge、合成原件与隔离后端；包含手机、响应丢失和版本冲突。"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ARTIFACT = Path(__file__).resolve().parents[2]/'.ai/tasks/2026-10-03-patient-reports/artifacts/t2'


def main():
    api, web = os.environ['REPORTS_API_URL'], os.environ['REPORTS_WEB_URL']
    assert all(urlsplit(url).hostname in {'127.0.0.1', 'localhost'} for url in [api, web])
    assert urlsplit(os.environ['DATABASE_URL']).path.startswith('/medaxis_demo_e2e_')
    token, other = os.environ['REPORTS_BROWSER_TOKEN'], os.environ['REPORTS_OTHER_TOKEN']
    auth = {'Authorization': f'Bearer {token}'}
    checks, errors, paths = [], [], []
    mode = {'fail_list': False}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        def bridge(route):
            path, query = urlsplit(route.request.url).path, urlsplit(route.request.url).query
            paths.append((path, route.request.method))
            if path == '/api/v1/patient/reports' and route.request.method == 'GET' and mode['fail_list']:
                return route.fulfill(status=503, json={'detail': '合成列表加载失败'})
            # 文件通过真实浏览器和 Vite 字节代理传输。CDP route.fetch 的 multipart body 可能省略文件字节。
            route.continue_()
        context.route('**/api/v1/**', bridge)
        page = context.new_page()
        # 真实后端完成归档后，让调用方丢失第一次成功响应；验证原提交键重试。
        page.add_init_script("""(() => {
            const original = window.fetch.bind(window); let lose = true;
            window.fetch = async (input, init) => {
                const response = await original(input, init);
                if (lose && String(input).endsWith('/patient/reports') && init?.method === 'POST' && response.ok) {
                    lose = false; throw new TypeError('Synthetic response lost after commit');
                }
                return response;
            };
        })();""")
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(web)
            page.evaluate("token => {localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)
            page.goto(f'{web}/reports')
            expect(page.get_by_text('还没有检查报告', exact=True)).to_be_visible()
            assert [] == context.request.get(f'{api}/api/v1/patient/cases', headers=auth).json()
            checks.append('独立入口与真实空态：无问诊病例也可上传')
            page.get_by_role('button', name='上传检查报告', exact=True).click()
            dialog = page.get_by_role('dialog')
            picker = dialog.get_by_label('选择报告文件')
            picker.set_input_files([str(ARTIFACT/'report-one.png'), str(ARTIFACT/'broken.png')])
            first = dialog.get_by_role('region', name='第1份报告', exact=True)
            second = dialog.get_by_role('region', name='第2份报告', exact=True)
            first.get_by_label('报告名称', exact=False).fill('浏览器合成血常规')
            first.get_by_label('医院或机构', exact=True).fill('浏览器合成医院')
            first.get_by_role('combobox', name='报告类别').click()
            page.get_by_role('option', name='检验报告', exact=True).click()
            first.get_by_role('button', name='添加到这份报告').click()
            picker.set_input_files(str(ARTIFACT/'report-two.png'))
            first.get_by_role('button', name='文件2上移', exact=True).click()
            first.get_by_role('checkbox').check(); second.get_by_role('checkbox').check()
            dialog.get_by_role('button', name='保存原件', exact=True).click()
            expect(first.get_by_role('alert')).to_contain_text('归档结果暂未确认')
            expect(second.get_by_role('alert')).to_be_visible()
            expect(first.get_by_label('报告名称', exact=False)).to_be_disabled()
            result = context.request.get(f'{api}/api/v1/patient/reports', headers=auth).json()
            assert 1 == result['total'] and 2 == result['items'][0]['file_count'] == result['items'][0]['page_count']
            assert ['report-two.png', 'report-one.png'] == [file['filename'] for file in result['items'][0]['files']]
            report = result['items'][0]
            assert report['examination_date'] is None and report['report_date'] is None
            dialog.get_by_role('button', name='暂收起（保留待处理项）', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='待处理提交')).to_be_visible()
            page.get_by_role('button', name='继续处理', exact=True).click()
            expect(first.get_by_role('alert')).to_contain_text('归档结果暂未确认')
            dialog.get_by_role('button', name='重试未完成项', exact=True).click()
            expect(dialog.get_by_role('status')).to_contain_text('1 / 2')
            expect(second.get_by_role('alert')).to_be_visible()
            assert 1 == context.request.get(f'{api}/api/v1/patient/reports', headers=auth).json()['total']
            second.get_by_role('button', name='取消此份', exact=True).click()
            dialog.get_by_role('button', name='完成', exact=True).click()
            checks.append('有序多页归为1份；批次部分失败保留成功；响应丢失同编号重试无重复')
            page.reload()
            page.get_by_role('link', name='查看报告', exact=True).click()
            expect(page.get_by_role('img', name='报告原件', exact=True)).to_be_visible()
            expect(page.get_by_text('文件 1 / 2', exact=True)).to_be_visible()
            page.get_by_role('button', name='放大原件').click()
            expect(page.get_by_text('125%', exact=True)).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role('link', name='下载原件', exact=True).click()
            assert (ARTIFACT/'report-two.png').read_bytes() == Path(download.value.path()).read_bytes()
            page.get_by_role('button', name='下一个文件').click()
            expect(page.get_by_text('文件 2 / 2', exact=True)).to_be_visible()
            expect(page.get_by_role('img', name='报告原件', exact=True)).to_be_visible()
            page.get_by_label('检查日期', exact=True).fill('2026-09-25')
            page.get_by_label('备注', exact=True).fill('浏览器对照原件补充日期')
            page.get_by_role('button', name='保存报告信息', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('报告信息已保存')
            report = context.request.get(f'{api}/api/v1/patient/reports/{report["id"]}', headers=auth).json()
            assert '2026-09-25' == report['examination_date'] and 1 == report['revision']
            checks.append('原件缩放/文件切换/下载字节一致；日期和备注真实持久化')
            page.screenshot(path=str(ARTIFACT/'reports-desktop-detail.png'), full_page=True)
            edit = {key: report[key] for key in ['title', 'category', 'institution', 'examination_date', 'report_date', 'notes']}
            edit.update(title='另一个窗口的最新标题', expected_revision=report['revision'])
            assert 200 == context.request.patch(f'{api}/api/v1/patient/reports/{report["id"]}', headers=auth, data=edit).status
            page.get_by_label('报告名称', exact=False).fill('本窗口未保存标题')
            page.get_by_role('button', name='保存报告信息', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('其他页面更新')
            expect(page.get_by_label('报告名称', exact=False)).to_have_value('本窗口未保存标题')
            page.get_by_role('button', name='对照最新版本', exact=True).click()
            expect(page.get_by_text('服务端最新信息', exact=False)).to_be_visible()
            expect(page.get_by_label('报告名称', exact=False)).to_have_value('本窗口未保存标题')
            page.get_by_role('button', name='放弃本页未保存填写，载入最新信息', exact=True).click()
            expect(page.get_by_label('报告名称', exact=False)).to_have_value('另一个窗口的最新标题')
            checks.append('并发信息修改拒绝旧版本；本页填写保留并可对照最新内容')
            page.goto(f'{web}/reports')
            page.get_by_label('搜索名称、医院或日期', exact=True).fill('查不到的合成报告')
            page.get_by_role('button', name='搜索', exact=True).click()
            expect(page.get_by_text('没有符合条件的报告', exact=True)).to_be_visible()
            page.get_by_role('button', name='清除筛选', exact=True).click()
            expect(page.get_by_text('另一个窗口的最新标题', exact=True)).to_be_visible()
            page.get_by_label('搜索名称、医院或日期', exact=True).fill('2026-09-25')
            page.get_by_role('button', name='搜索', exact=True).click()
            expect(page.get_by_text('共找到 1 份报告', exact=True)).to_be_visible()
            mode['fail_list'] = True
            page.reload()
            expect(page.get_by_role('alert')).to_contain_text('合成列表加载失败')
            mode['fail_list'] = False
            page.get_by_role('button', name='重试', exact=True).click()
            expect(page.get_by_text('共找到 1 份报告', exact=True)).to_be_visible()
            page.screenshot(path=str(ARTIFACT/'reports-desktop-list.png'), full_page=True)
            checks.append('日期搜索、无结果与未上传空态区分；列表失败可重试')
            assert not any('/documents/' in path or '/ai-actions/' in path for path, _ in paths)
            assert 404 == context.request.get(f'{api}/api/v1/patient/reports/{report["id"]}', headers={'Authorization': f'Bearer {other}'}).status
            assert 404 == context.request.get(f'{api}/api/v1/patient/reports/{report["id"]}/files/{report["files"][0]["id"]}', headers={'Authorization': f'Bearer {other}'}).status
            # 新浏览器上下文模拟另一设备重新登录；资料从服务器恢复，不依赖旧页面状态。
            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, device_scale_factor=1)
            mobile.route('**/api/v1/**', bridge)
            phone = mobile.new_page(); phone.on('pageerror', lambda error: errors.append(str(error)))
            phone.goto(web); phone.evaluate("token => {localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}", token)
            phone.goto(f'{web}/reports')
            expect(phone.get_by_text('另一个窗口的最新标题', exact=True)).to_be_visible()
            phone.get_by_role('button', name='更多功能', exact=True).click()
            phone.get_by_role('dialog', name='更多功能', exact=True).get_by_role('button', name='检查报告', exact=True).click()
            phone.get_by_role('link', name='查看报告', exact=True).click()
            phone.get_by_role('tab', name='查看原件', exact=True).click()
            expect(phone.get_by_role('img', name='报告原件', exact=True)).to_be_visible()
            phone.screenshot(path=str(ARTIFACT/'reports-mobile-original.png'), full_page=True)
            phone.get_by_role('tab', name='报告信息', exact=True).click()
            phone.get_by_label('备注', exact=True).fill('手机端补充备注')
            phone.get_by_role('button', name='保存报告信息', exact=True).click()
            expect(phone.get_by_role('alert')).to_contain_text('报告信息已保存')
            phone.screenshot(path=str(ARTIFACT/'reports-mobile-info.png'), full_page=True)
            assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            phone.get_by_role('link', name='返回报告列表', exact=True).click()
            phone.get_by_role('button', name='上传检查报告', exact=True).click()
            modal = phone.get_by_role('dialog')
            modal.get_by_label('选择报告文件').set_input_files(str(ARTIFACT/'report-three.pdf'))
            modal.get_by_role('checkbox').check()
            modal.get_by_role('button', name='保存原件', exact=True).click()
            expect(modal.get_by_role('status')).to_contain_text('1 / 1')
            modal.get_by_role('button', name='完成', exact=True).click()
            pdf = context.request.get(f'{api}/api/v1/patient/reports', headers=auth).json()['items'][0]
            assert 2 == pdf['page_count'] and 1 == pdf['file_count']
            phone.goto(f'{web}/reports/{pdf["id"]}')
            phone.get_by_role('tab', name='查看原件', exact=True).click()
            expect(phone.get_by_title('PDF报告原件')).to_be_visible()
            expect(phone.get_by_role('link', name='下载原件', exact=True)).to_be_enabled()
            assert 2 == context.request.get(f'{api}/api/v1/patient/reports', headers=auth).json()['stats']['archived']
            mobile.close()
            checks.append('新设备登录恢复；手机导航、原件标签、信息保存、PDF上传及安全预览入口')
            assert not errors, errors
            (ARTIFACT/'browser-result.json').write_text(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False), flush=True)
        except Exception:
            page.screenshot(path=str(ARTIFACT/'reports-failure.png'), full_page=True)
            (ARTIFACT/'reports-failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
            raise
        finally:
            browser.close()


if __name__ == '__main__': main()
