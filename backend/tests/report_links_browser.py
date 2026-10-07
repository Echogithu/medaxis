"""真实Edge病例引用；只用合成JWT、病例和报告，所有引用API真实。"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from playwright.sync_api import expect, sync_playwright


def main():
    api, web = os.environ['REPORTS_API_URL'], os.environ['REPORTS_WEB_URL']
    assert all(urlsplit(url).hostname in {'127.0.0.1','localhost'} for url in [api,web])
    database=urlsplit(os.environ['DATABASE_URL'])
    assert database.hostname in {'127.0.0.1','localhost'} and database.path.startswith('/medaxis_demo_e2e_')
    artifact=Path(os.environ['REPORTS_REVIEW_ARTIFACT']);token=os.environ['REPORTS_BROWSER_TOKEN']
    auth={'Authorization':'Bearer '+token};errors=[];checks=[];paths=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page();page.set_default_timeout(20000)
        page.on('pageerror',lambda error:errors.append(str(error)))
        context.on('request',lambda request:paths.append(urlsplit(request.url).path))
        def login(target):
            target.goto(web)
            target.evaluate("token=>{localStorage.setItem('access_token',token);localStorage.setItem('user_role','patient');}",token)
        try:
            cases=[]
            for index in range(12):
                response=context.request.post(api+'/api/v1/medical-cases',headers=auth,data={'title':f'合成病例{index:02}'})
                assert response.status==201;cases.append(response.json())
            response=context.request.post(api+'/api/v1/patient/reports',headers=auth,multipart={
                'metadata':json.dumps({'request_id':str(uuid4()),'title':'合成病例引用报告','category':'lab','ownership_declared':True}),
                'files':{'name':'synthetic-report.png','mimeType':'image/png','buffer':(artifact/'synthetic-report.png').read_bytes()}})
            assert response.status==201;report=response.json();base='/api/v1/patient/reports/'+report['id']
            def state():
                response=context.request.get(api+base+'/case-links',headers=auth);assert response.status==200;return response.json()
            def body(view,ids):
                return {'request_id':str(uuid4()),'expected_links_revision':view['links_revision'],
                    'expected_review_revision':view['review_revision'],'expected_source_hash':view['source_hash'],
                    'case_ids':ids,'refresh_case_ids':[]}
            login(page);page.goto(web+'/reports/'+report['id'])
            panel=page.get_by_role('region',name='报告病例关联',exact=True)
            expect(panel.get_by_text('还没有关联病例；报告已独立归档。',exact=True)).to_be_visible()
            panel.get_by_role('button',name='选择关联病例',exact=True).click()
            modal=page.get_by_role('dialog',name='选择本人的病例',exact=True)
            modal.get_by_role('checkbox',name='合成病例11',exact=True).check()
            modal.get_by_role('button',name='Go to page 2',exact=True).click()
            modal.get_by_role('checkbox',name='合成病例01',exact=True).check()
            expect(modal.get_by_text('共选择 2 个病例（保留其他页的选择）',exact=True)).to_be_visible()
            page.evaluate("""(()=>{const original=window.fetch.bind(window);let lose=true;window.fetch=async(input,init)=>{
              const response=await original(input,init);if(lose&&String(input).endsWith('/case-links')&&init?.method==='POST'&&response.ok){lose=false;throw new TypeError('Synthetic links response lost');}return response;};})();""")
            modal.get_by_role('button',name='保存病例关联',exact=True).click()
            expect(modal.get_by_role('button',name='使用原编号重试关联',exact=True)).to_be_enabled()
            first=state();assert len(first['items'])==2 and first['links_revision']==1
            modal.get_by_role('button',name='使用原编号重试关联',exact=True).click()
            expect(modal).not_to_be_visible()
            assert state()['links_revision']==1
            page.reload();expect(panel.get_by_text('合成病例11',exact=True)).to_be_visible()
            checks.append('跨页选择保留；保存成功丢响应可在弹窗内原编号重试，仅1次修订；刷新恢复真实关联')
            panel.get_by_text('合成病例11',exact=True).locator('..').get_by_role('link',name='查看病例',exact=True).click()
            linked=page.get_by_role('region',name='病例关联报告',exact=True)
            expect(linked.get_by_text('合成病例引用报告',exact=True)).to_be_visible()
            linked.get_by_role('link',name='查看独立报告',exact=True).click()
            expect(panel).to_be_visible()
            panel.get_by_role('button',name='选择关联病例',exact=True).click()
            modal.get_by_label('搜索病例名称',exact=True).fill('合成病例05')
            modal.get_by_role('button',name='搜索',exact=True).click()
            modal.get_by_role('checkbox',name='合成病例05',exact=True).check()
            expect(modal.get_by_text('共选择 3 个病例（保留其他页的选择）',exact=True)).to_be_visible()
            current=state()
            response=context.request.post(api+base+'/case-links',headers=auth,data=body(current,[item['case_id'] for item in current['items']]+[cases[4]['id']]))
            assert response.status==200
            modal.get_by_role('button',name='保存病例关联',exact=True).click()
            expect(modal.get_by_text('关联或报告来源已在其他页面更新，请刷新对照后重新选择 选择仍保留；请对照最新关联。',exact=True)).to_be_visible()
            expect(modal.get_by_role('checkbox',name='合成病例05',exact=True)).to_be_checked()
            modal.get_by_role('button',name='放弃本页选择，载入最新关联',exact=True).click()
            expect(modal.get_by_role('checkbox',name='合成病例05',exact=True)).not_to_be_checked()
            modal.get_by_role('button',name='暂不保存',exact=True).click()
            assert len(state()['items'])==3
            checks.append('病例详情独立引用入口可往返；搜索不丢其他页选择；真实第二窗口更新导致409，保留选择，明确放弃才重载')
            fields={key:report[key] for key in ['title','category','institution','examination_date','report_date','notes']}
            response=context.request.patch(api+base,headers=auth,data=fields|{'expected_revision':report['revision'],'category':'other'})
            assert response.status==200
            page.reload()
            row=panel.get_by_text('合成病例11',exact=True).locator('..')
            expect(row.get_by_text('报告来源已变化，关联待更新',exact=True)).to_be_visible()
            row.get_by_role('button',name='更新为当前来源',exact=True).click()
            expect(row.get_by_text('关联原件，尚未本人核对',exact=True)).to_be_visible()
            assert len([item for item in state()['items'] if item['status']=='source_changed'])==2
            panel.scroll_into_view_if_needed();page.screenshot(path=str(artifact/'desktop-links.png'),full_page=True,animations='disabled')
            row=panel.get_by_text('合成病例01',exact=True).locator('..')
            row.get_by_role('button',name='解除关联',exact=True).click()
            expect(panel.get_by_text('合成病例01',exact=True)).not_to_be_visible()
            assert len(state()['items'])==2
            checks.append('类别变化保留旧引用并提示，显式更新仅指定病例；解除一条不删其他引用或报告')
            phone_context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True)
            phone=phone_context.new_page();phone.on('pageerror',lambda error:errors.append(str(error)))
            login(phone);phone.goto(web+'/reports/'+report['id'])
            ppanel=phone.get_by_role('region',name='报告病例关联',exact=True)
            ppanel.get_by_role('button',name='选择关联病例',exact=True).click()
            pmodal=phone.get_by_role('dialog',name='选择本人的病例',exact=True)
            pmodal.get_by_label('搜索病例名称',exact=True).fill('合成病例05')
            pmodal.get_by_role('button',name='搜索',exact=True).click()
            pmodal.get_by_role('checkbox',name='合成病例05',exact=True).check()
            pmodal.get_by_role('button',name='保存病例关联',exact=True).click();expect(pmodal).not_to_be_visible()
            expect(ppanel.get_by_text('合成病例05',exact=True)).to_be_visible()
            ppanel.scroll_into_view_if_needed();assert phone.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            phone.screenshot(path=str(artifact/'mobile-links.png'),full_page=True,animations='disabled')
            phone_context.close();checks.append('新390px手机从服务端恢复，搜索/选择/保存可操作，无横向溢出')
            original=context.request.get(api+base+'/files/'+report['files'][0]['id'],headers=auth).body()
            assert context.request.delete(api+'/api/v1/medical-cases/'+cases[11]['id'],headers=auth).status==204
            page.reload();expect(panel.get_by_text('合成病例11',exact=True)).not_to_be_visible()
            assert original==context.request.get(api+base+'/files/'+report['files'][0]['id'],headers=auth).body()
            assert not errors and not any(path.endswith('/ai') or path.endswith('/extract') for path in paths)
            checks.append('真实删除病例只撤引用，独立报告和原件字节保留；全程无AI或取字调用')
            result={'passed':checks,'page_errors':errors,'auth':'synthetic JWT; actual login form not covered','models':'no model or OCR calls'}
            (artifact/'browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False),flush=True)
        except Exception:
            page.screenshot(path=str(artifact/'failure.png'),full_page=True,animations='disabled')
            (artifact/'failure-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            raise
        finally:browser.close()


if __name__=='__main__':main()
