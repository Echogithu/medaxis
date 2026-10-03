"""Edge + 真实隔离 API/数据库验收随访患者操作，不调用真实模型或邮件。"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect


def main():
    api,web=os.environ['FOLLOWUP_API_URL'],os.environ['FOLLOWUP_WEB_URL']
    for target in [api,web]:
        parsed=urlsplit(target)
        assert parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost'}
    assert urlsplit(os.environ['DATABASE_URL']).path.startswith('/medaxis_demo_e2e_')
    token=os.environ['FOLLOWUP_BROWSER_TOKEN']
    artifact=Path(__file__).resolve().parents[2]/'.ai/tasks/2026-10-03-health-followup-workspace/followup'
    cases,errors=[],[]
    date=datetime.now(timezone(timedelta(hours=8))).date()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL','msedge'),headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1050})
        mode={'fail_create':False,'fail_list':False,'fail_check':False}
        def bridge(route):
            path=urlsplit(route.request.url).path
            if path.endswith('/care-plans') and route.request.method=='POST' and mode['fail_create']:
                mode['fail_create']=False
                # 服务器已提交但客户端只收到500：重试仍只能生成一条。
                route.fetch(url=f'{api}{path}')
                return route.fulfill(status=500,json={'detail':'合成创建响应丢失'})
            if path.endswith('/care-plans') and route.request.method=='GET' and mode['fail_list']:
                mode['fail_list']=False
                return route.fulfill(status=500,json={'detail':'合成列表失败'})
            if path.endswith('/check-in') and mode['fail_check']:
                mode['fail_check']=False
                return route.fulfill(status=500,json={'detail':'合成执行失败'})
            query=urlsplit(route.request.url).query
            response=route.fetch(url=f'{api}{path}'+(f'?{query}' if query else ''))
            route.fulfill(response=response)
        context.route('**/api/v1/**',bridge)
        page=context.new_page(); page.on('pageerror',lambda error:errors.append(str(error)))
        auth={'Authorization':f'Bearer {token}'}
        def select(label,choice):
            # 实际 ARIA snapshot：MUI 下拉名称包含“标签 + 当前值”。
            page.get_by_role('combobox',name=label,exact=False).click()
            page.get_by_role('option',name=choice,exact=True).click()
        def filtered(choice):
            if choice in ['进行中', '已完成', '全部']:
                page.get_by_role('tab', name='全部计划' if choice == '全部' else choice, exact=True).click()
            else: select('其他状态', choice)
        def do_action(card,name):
            card.get_by_role('button',name=name,exact=True).click()
            page.get_by_role('button',name='确定',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
        try:
            page.goto(web); page.evaluate("token=>{localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}",token)
            page.goto(f'{web}/followups')
            expect(page.get_by_text('暂无随访计划',exact=True)).to_be_visible(timeout=15000)
            page.get_by_role('button',name='新建随访计划').click()
            page.get_by_label('计划名称',exact=False).fill('浏览器闭环计划')
            page.get_by_label('结束日期',exact=False).fill((date+timedelta(days=5)).isoformat())
            page.get_by_label('任务 1 内容',exact=False).fill('合成复查任务')
            select('关联病历（可选）','浏览器随访来源病历')
            page.get_by_role('button',name='添加任务',exact=True).click()
            select('任务 2 类型','自测')
            page.get_by_label('任务 2 内容',exact=False).fill('合成自测任务')
            page.get_by_label('任务 2 数值单位（可选）',exact=True).fill('单位')
            mode['fail_create']=True
            page.get_by_role('button',name='保存待确认计划',exact=True).click()
            expect(page.get_by_text('合成创建响应丢失；当前填写已保留。',exact=True)).to_be_visible()
            expect(page.get_by_label('计划名称',exact=False)).to_have_value('浏览器闭环计划')
            page.get_by_role('button',name='保存待确认计划',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            card=page.get_by_role('heading',name='浏览器闭环计划',exact=True).locator('xpath=ancestor::*[contains(@class,"MuiCard-root")][1]')
            expect(card.get_by_text('待确认',exact=True)).to_be_visible()
            expect(card.get_by_text('患者录入',exact=False)).to_be_visible()
            all_plans=context.request.get(f'{api}/api/v1/patient/care-plans',headers=auth).json()
            assert 1==len(all_plans)
            plan=all_plans[0]
            assert plan['source_case_id'] and len(plan['tasks'])==2
            expect(card.get_by_role('link',name='关联病历：浏览器随访来源病历')).to_have_attribute('href',f'/cases?case_id={plan["source_case_id"]}')
            cases.append('实际页面创建、病历关联、响应丢失重试幂等且保留填写')
            card.get_by_role('button',name='编辑计划',exact=True).click()
            page.get_by_label('计划说明',exact=True).fill('编辑后保存说明')
            page.get_by_role('button',name='保存待确认计划',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            expect(card.get_by_text('编辑后保存说明',exact=True)).to_be_visible()
            card.get_by_role('button',name='编辑计划',exact=True).click()
            page.get_by_label('计划说明',exact=True).fill('冲突时保留的填写')
            current=context.request.get(f'{api}/api/v1/patient/care-plans/{plan["id"]}',headers=auth).json()
            external={key:current[key] for key in ['title','source_case_id','start_date','end_date']}
            external.update(description='另一页面更新说明',expected_revision=current['revision'],
                tasks=[{key:task[key] for key in ['id','type','description','due_date','unit']} for task in current['tasks']])
            assert 200==context.request.patch(f'{api}/api/v1/patient/care-plans/{plan["id"]}',headers=auth,data=external).status
            page.get_by_role('button',name='保存待确认计划',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='计划已被更新')).to_be_visible()
            expect(page.get_by_label('计划说明',exact=True)).to_have_value('冲突时保留的填写')
            page.get_by_role('button',name='放弃当前填写并重新加载',exact=True).click()
            expect(card.get_by_text('另一页面更新说明',exact=True)).to_be_visible()
            cases.append('编辑409不覆盖新版本，保留填写，明确放弃后可重新加载')
            assert card.get_by_role('checkbox').first.is_disabled()
            do_action(card,'确认执行')
            filtered('进行中')
            expect(card.get_by_text('进行中',exact=True)).to_be_visible()
            cases.append('待确认可编辑，确认前禁止执行，确认后来源仍患者录入')
            do_action(card,'暂停计划')
            filtered('已暂停')
            expect(card.get_by_text('已暂停',exact=True)).to_be_visible()
            assert card.get_by_role('checkbox').first.is_disabled()
            do_action(card,'恢复计划')
            filtered('进行中')
            expect(card.get_by_text('进行中',exact=True)).to_be_visible()
            cases.append('暂停与恢复在页面和API一致，暂停阻止执行')
            card.get_by_role('checkbox', name='标记完成：合成自测任务', exact=True).click()
            page.get_by_role('button',name='保存并完成任务',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='请选择症状变化并填写本次反馈')).to_be_visible()
            select('症状变化', '基本稳定')
            select('用药情况（可选）', '暂无用药')
            page.get_by_label('自测数值（单位）',exact=True).fill('123.4')
            page.get_by_label('本次反馈与想问医生的问题',exact=False).fill('浏览器合成执行记录')
            page.screenshot(path=str(artifact/'followup-feedback-desktop.png'),full_page=True)
            for width in [320,390,768]:
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path=str(artifact/'followup-feedback-tablet.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1050})
            mode['fail_check']=True
            page.get_by_role('button',name='保存并完成任务',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='合成执行失败；填写内容已保留。')).to_be_visible()
            expect(page.get_by_label('自测数值（单位）',exact=True)).to_have_value('123.4')
            page.get_by_role('button',name='保存并完成任务',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            expect(card.get_by_text('进度 50%',exact=True)).to_be_visible()
            page.reload()
            card=page.get_by_role('heading',name='浏览器闭环计划',exact=True).locator('xpath=ancestor::*[contains(@class,"MuiCard-root")][1]')
            expect(card.get_by_text('浏览器合成执行记录',exact=False)).to_be_visible()
            mode['fail_check']=True
            card.get_by_role('checkbox',name='标记完成：合成复查任务',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='合成执行失败')).to_be_visible()
            expect(card.get_by_role('checkbox',name='标记完成：合成复查任务',exact=True)).not_to_be_checked()
            card.get_by_role('checkbox',name='标记完成：合成复查任务',exact=True).click()
            expect(card.get_by_role('checkbox',name='已完成：合成复查任务',exact=True)).to_be_checked()
            expect(card.get_by_text('进度 100%',exact=True)).to_be_visible()
            expect(page.get_by_role('alert').filter(has_text='合成执行失败')).not_to_be_visible()
            expect(card.get_by_text('已完成',exact=True)).to_be_visible()
            cases.append('执行500保留数值备注，刷新恢复，最后任务自动完成计划')
            assert '症状变化：基本稳定' in context.request.get(f'{api}/api/v1/patient/care-plans/{plan["id"]}',headers=auth).json()['tasks'][1]['completion_notes']
            cases.append('自测勾选打开反馈，必填校验、症状与用药反馈真实保存；普通复查勾选直接持久化')
            page.screenshot(path=str(artifact/'followup-desktop.png'),full_page=True)
            # 用真实创建API补13条计划，验收页面分页而非mock列表。
            for index in range(13):
                response=context.request.post(f'{api}/api/v1/patient/care-plans',headers=auth,data={
                    'request_id':str(uuid4()),'title':f'分页计划{index}','start_date':date.isoformat(),'end_date':date.isoformat(),
                    'tasks':[{'description':'分页任务','due_date':date.isoformat()}]})
                assert response.status==201
            page.reload()
            expect(page.get_by_role('button',name='加载更多计划',exact=True)).to_be_visible()
            mode['fail_list']=True
            page.get_by_role('button',name='加载更多计划',exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='合成列表失败')).to_be_visible()
            assert page.get_by_text('暂无随访计划',exact=True).count()==0
            page.get_by_role('button',name='重试',exact=True).click()
            expect(page.get_by_text('浏览器闭环计划',exact=True)).to_be_visible()
            assert page.get_by_role('button',name='编辑计划',exact=True).count()==13
            cases.append('超过10条可逐页加载，分页失败保留列表并可重试')
            page.get_by_text('分页计划0',exact=True).locator('xpath=ancestor::*[contains(@class,"MuiCard-root")][1]').get_by_role('button',name='取消计划',exact=True).click()
            page.get_by_role('button',name='确定',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            filtered('已取消')
            expect(page.get_by_text('分页计划0',exact=True)).to_be_visible()
            assert page.get_by_role('button',name='确认执行',exact=True).count()==0
            cases.append('取消后不可恢复或执行，状态筛选持久一致')
            page.set_viewport_size({'width':390,'height':844})
            filtered('全部')
            expect(page.get_by_role('button',name='新建随访计划')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.get_by_role('button',name='新建随访计划').click()
            page.get_by_label('计划名称',exact=False).fill('手机无效日期')
            page.get_by_label('任务 1 内容',exact=False).fill('手机任务')
            page.get_by_label('任务 1 日期',exact=False).fill((date+timedelta(days=1)).isoformat())
            page.get_by_role('button',name='保存待确认计划',exact=True).click()
            expect(page.get_by_text('任务日期必须在计划起止日期内，结束日期不能早于开始日期',exact=True)).to_be_visible()
            page.screenshot(path=str(artifact/'followup-mobile.png'),full_page=True)
            for width in [320, 768]:
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            cases.append('390px布局无横向溢出，非法日期明确阻止提交')
            assert not errors,errors
        except Exception:
            page.screenshot(path=str(artifact/'followup-browser-failure.png'),full_page=True)
            (artifact/'browser-failure-state.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            (artifact/'browser-failure-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            raise
        finally:
            (artifact/'browser-followup-results.json').write_text(json.dumps({'cases':cases,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps({'cases':cases,'page_errors':errors},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
