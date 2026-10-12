"""将真实模型+真实检索产物交给实际页面验证；身份/历史API为合成替身。"""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, REPORT, token, events, ready, send
from report_reading_browser import seed_report

def main():
    artifact=Path(os.environ['REAL_REPORT_ARTIFACT'])
    report=json.loads(artifact.read_text(encoding='utf-8'))['report']
    assert report['knowledge_citations'] and report['knowledge_retrieval_status']=='used'
    saved=seed_report()
    REPORT.clear(); REPORT.update(report)
    artifacts=Path(os.environ['REPORT_SCREENSHOT_DIR']); artifacts.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL','msedge'),headless=True)
        try:
            page=browser.new_page(viewport={'width':1440,'height':1000})
            api=MockAPI(); page.route('**/api/v1/**',api.route)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('''([jwt,saved])=>{localStorage.setItem('access_token',jwt);localStorage.setItem('user_role','patient');localStorage.setItem('medaxis.chat-history.v1:user:reading-test',JSON.stringify(saved));}''',[token('reading-test'),saved])
            page.goto(f'{BASE}/chat')
            page.get_by_role('button',name='查看问诊总结',exact=True).last.click()
            dialog=page.get_by_role('dialog',name='这次问诊总结')
            link=dialog.get_by_role('link',name=re.compile(r'引用 S\d+，查看来源')).first
            citation_id=re.search(r'S\d+',link.get_attribute('aria-label')).group(0)
            link.click()
            citation=next(c for c in report['knowledge_citations'] if c['citation_id']==citation_id)
            card=dialog.get_by_role('article',name=f'参考资料 {citation_id}',exact=True)
            expect(card).to_be_visible();expect(card).to_be_focused()
            expect(card.get_by_text(citation['title'],exact=True)).to_be_visible()
            card.get_by_role('button',name=f'查看 {citation_id} 原文片段').click()
            expect(card.get_by_role('region',name=f'{citation_id} 原文片段')).to_be_visible()
            assert citation['excerpt'] in card.get_by_role('region',name=f'{citation_id} 原文片段').inner_text()
            assert '这次没有找到能核对的参考资料' not in dialog.inner_text()
            page.wait_for_timeout(350)
            page.screenshot(path=str(artifacts/'real-report-source-1440.png'))
            page.set_viewport_size({'width':390,'height':1000})
            assert dialog.get_by_role('region',name='问诊总结正文').evaluate('el=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(artifacts/'real-report-source-390.png'))
            assert not errors,errors
            print('PASS: 真实模型+真实知识库报告显示实际来源、编号跳转及完整原文；1440/390无溢出')
            dialog.get_by_role('button',name='关闭问诊总结',exact=True).click()
            # 明确检索失败时，实际UI只能显示错误，不得出现新诊断总结。
            page.get_by_role('button',name='新建会话',exact=True).last.click()
            def fail_search(route):
                route.fulfill(status=200,content_type='text/event-stream',body=events(('error',{'code':'MEDICAL_EVIDENCE_UNAVAILABLE','error':'未获得可核验的医学参考资料，本次未生成诊断报告。请重试检索。'})))
            page.route('**/api/v1/agents/route/stream',fail_search)
            ready(page);send(page,'合成检索失败主诉')
            expect(page.get_by_text('❌ 错误: 未获得可核验的医学参考资料，本次未生成诊断报告。请重试检索。',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='查看问诊总结',exact=True)).to_have_count(0)
            ready(page)
            print('PASS: 缺少证据时显示明确错误，不生成或展示成功报告，输入可继续使用')
            page.unroute('**/api/v1/agents/route/stream',fail_search)
            page.get_by_role('button',name='新建会话',exact=True).last.click()
            def initial_interview(route):
                route.fulfill(status=200,content_type='text/event-stream',body=events(
                    ('question',{'questions':[{'question_id':'q1','question':'持续多久？','type':'choice','options':['一天','两天']}]}),
                    ('complete',{'status':'waiting_for_answer','session_id':'retry-evidence'})))
            page.route('**/api/v1/agents/route/stream',initial_interview)
            retry_count=0
            def retry_search(route):
                nonlocal retry_count
                retry_count+=1
                body=events(('error',{'code':'MEDICAL_EVIDENCE_UNAVAILABLE','error':'检索失败，本次未生成报告。请重试检索。'})) if retry_count==1 else events(('structured',report),('complete',{'status':'completed','session_id':'retry-evidence','case_id':'demo-case-a'}))
                route.fulfill(status=200,content_type='text/event-stream',body=body)
            page.route('**/api/v1/agents/route/stream/continue**',retry_search)
            ready(page);send(page,'合成证据重试状态')
            option=page.get_by_role('button',name='一天',exact=True)
            expect(option).to_be_enabled();option.click()
            expect(page.get_by_text('❌ 错误: 检索失败，本次未生成报告。请重试检索。',exact=True)).to_be_visible()
            ready(page);expect(option).to_be_enabled();option.click()
            expect(page.get_by_role('dialog',name='这次问诊总结')).to_be_visible()
            page.get_by_role('dialog',name='这次问诊总结').get_by_role('button',name='关闭问诊总结',exact=True).click()
            expect(page.get_by_role('button',name='查看问诊总结',exact=True).last).to_be_visible()
            assert retry_count==2 and not errors,(retry_count,errors)
            print('PASS: 题卡检索失败后仍可重试，同会话第二次成功显示带来源报告')
        finally: browser.close()

if __name__=='__main__': main()
