"""真实 Edge 页面与随机隔离 API，模型及入队边界替换为合成测试。"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect


def main():
    api, web, token = os.environ['POSTVISIT_API_URL'], os.environ['POSTVISIT_WEB_URL'], os.environ['POSTVISIT_BROWSER_TOKEN']
    assert all(urlsplit(s).hostname in {'127.0.0.1','localhost'} for s in [api,web])
    assert urlsplit(os.environ['DATABASE_URL']).path.startswith('/medaxis_demo_e2e_')
    artifact = Path(__file__).resolve().parents[2]/'.ai/tasks/2026-10-02-postvisit-ai-actions'
    auth={'Authorization':f'Bearer {token}'}
    checks, errors, calls = [], [], []
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport={'width':1280,'height':1000})
        mode={'fail_confirm':True}
        def bridge(route):
            path=urlsplit(route.request.url).path; query=urlsplit(route.request.url).query
            calls.append({'path':path,'method':route.request.method})
            if path.endswith('/ai-actions/confirm') and mode['fail_confirm']:
                mode['fail_confirm']=False
                return route.fulfill(status=500,json={'detail':'合成确认失败，请重试'})
            route.fulfill(response=route.fetch(url=f'{api}{path}'+(f'?{query}' if query else '')))
        context.route('**/api/v1/**',bridge)
        page=context.new_page(); page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            page.goto(web); page.evaluate("token=>{localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}",token)
            cases=context.request.get(f'{api}/api/v1/patient/cases',headers=auth).json()
            if isinstance(cases,dict): cases=cases.get('items',cases.get('cases',[]))
            case_id=cases[0]['id']
            target=f'{web}/cases?case_id={case_id}&stage=visit'
            page.goto(target)
            page.get_by_label('就诊情况',exact=True).fill('随访合成患者 电话13800000000。示例药每次1片每日08:00服用')
            page.get_by_label('需要复查的事项（每行一条）',exact=True).fill('三天后复查合成项目')
            page.get_by_role('button',name='保存就诊结果',exact=True).click()
            open_button=page.get_by_role('button',name='预览脱敏文本并整理',exact=True)
            expect(open_button).to_be_enabled(); open_button.click()
            dialog=page.get_by_role('dialog')
            expect(dialog.get_by_role('button',name='同意并整理')).to_be_disabled()
            assert '13800000000' not in dialog.inner_text()
            assert '随访合成患者' not in dialog.locator('pre').inner_text()
            assert not any(c['path'].endswith('/generate') for c in calls)
            dialog.get_by_role('button',name='取消',exact=True).click()
            checks.append('脱敏预览无模型调用；取消/未勾选同意不能发送')
            open_button.click()
            dialog.get_by_role('checkbox').check()
            dialog.get_by_role('button',name='同意并整理').click()
            expect(dialog).not_to_be_visible()
            expect(page.get_by_text('有待你确认的建议。',exact=False)).to_be_visible()
            assert [] == context.request.get(f'{api}/api/v1/patient/care-plans',headers=auth).json()
            assert [] == context.request.get(f'{api}/api/v1/patient/reminders',headers=auth).json()['items']
            checks.append('同意后生成候选，确认前不创建计划或事件')
            page.goto(f'{web}/followups')
            page.get_by_role('link',name='查看待确认建议 1',exact=True).click()
            expect(page.get_by_label('随访 1 日期')).to_be_visible()
            checks.append('刷新后保留候选，随访页提示并链接到诊后确认入口')
            date=(datetime.now(timezone(timedelta(hours=8))).date()+timedelta(days=1)).isoformat()
            page.get_by_role('checkbox',name='随访 1：三天后复查合成项目').check()
            page.get_by_role('checkbox',name='用药 1：示例药 · 1片').check()
            confirm=page.get_by_role('button',name='核对完毕，确认创建安排')
            confirm.click(); expect(page.get_by_role('alert').filter(has_text='请补齐')).to_be_visible()
            page.get_by_label('随访 1 日期').fill(date)
            page.get_by_label('用药 1 开始日期').fill(date)
            page.get_by_label('用药 1 结束日期').fill(date)
            page.get_by_label('用药 1 提醒时刻').fill('25:00')
            confirm.click(); expect(page.get_by_role('alert').filter(has_text='请核对日期范围')).to_be_visible()
            page.get_by_label('用药 1 提醒时刻').fill('08:00,20:00')
            confirm.click(); expect(page.get_by_role('alert').filter(has_text='合成确认失败')).to_be_visible()
            expect(page.get_by_label('用药 1 提醒时刻')).to_have_value('08:00,20:00')
            confirm.click(); expect(page.get_by_role('alert').filter(has_text='安排已确认')).to_be_visible()
            checks.append('缺失/非法排程阻止；确认失败保留填写，重试成功')
            assert 1 == len(context.request.get(f'{api}/api/v1/patient/care-plans',headers=auth).json())
            page.get_by_role('link',name='查看提醒',exact=True).click()
            expect(page).to_have_url(f'{web}/reminders')
            expect(page.get_by_text('示例药',exact=False).first).to_be_visible()
            assert 3 == len(context.request.get(f'{api}/api/v1/patient/reminders',headers=auth).json()['items'])
            checks.append('创建随访及UTC+8用药提醒；查看提醒路由可达')
            page.goto(target)
            page.get_by_label('就诊情况',exact=True).fill('修改来源，停止旧安排')
            expect(page.get_by_role('button',name='停用本次安排')).to_be_disabled()
            page.get_by_role('button',name='保存修改',exact=True).click()
            expect(page.get_by_role('button',name='预览脱敏文本并整理')).to_be_enabled()
            assert all(e['status']=='cancelled' for e in context.request.get(f'{api}/api/v1/patient/reminders',headers=auth).json()['items'])
            assert 'cancelled' == context.request.get(f'{api}/api/v1/patient/care-plans',headers=auth).json()[0]['status']
            checks.append('未保存内容禁用操作；来源更新取消旧提醒及关联计划')
            page.screenshot(path=str(artifact/'postvisit-final.png'),full_page=True)
            assert not errors,errors
            (artifact/'browser-result.json').write_text(json.dumps({'passed':checks,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':checks,'page_errors':errors},ensure_ascii=False),flush=True)
        except Exception:
            page.screenshot(path=str(artifact/'postvisit-failure.png'),full_page=True)
            (artifact/'browser-failure-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            raise
        finally: browser.close()


if __name__=='__main__': main()
