"""真实认证、API、PostgreSQL 的患者申请与医生回复；仅故障响应为合成注入。"""
import json
import base64
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from playwright.sync_api import sync_playwright, expect

ARTIFACT = Path(__file__).resolve().parents[2] / '.ai/tasks/2026-10-03-chat-doctor-handoff-entry'


def main():
    api, web = os.environ['CONSULTATION_API_URL'], os.environ['CONSULTATION_WEB_URL']
    for target in [api, web]:
        parsed = urlsplit(target)
        assert parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'} and not parsed.username
    database = urlsplit(os.environ['DATABASE_URL'])
    assert database.scheme == 'postgresql+asyncpg' and database.hostname in {'127.0.0.1', 'localhost'} and database.path.startswith('/medaxis_demo_e2e_')
    patient_token, doctor_token = os.environ['CONSULTATION_PATIENT_TOKEN'], os.environ['CONSULTATION_DOCTOR_TOKEN']
    case_id = os.environ['CONSULTATION_CASE_ID']
    mode, errors = {'create_lost': True, 'reply_lost': True}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        contexts = []
        def session(token, role):
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}); contexts.append(context)
            context.add_init_script(f"localStorage.setItem('access_token', {json.dumps(token)}); localStorage.setItem('user_role', {json.dumps(role)});")
            if role == 'patient':
                owner = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=='))['sub']
                saved = {'id': 'synthetic-chat', 'title': '浏览器合成问诊', 'created_at': '2026-10-03T00:00:00Z',
                    'updated_at': '2026-10-03T00:00:00Z', 'message_count': 1, 'messages': [{
                        'id': 'synthetic-message', 'role': 'agent', 'timestamp': '2026-10-03T00:00:00Z', 'content': '合成 AI 原始摘要'}],
                    'chatMode': 'diagnosed', 'reportData': None, 'reportCaseId': case_id, 'backendSessionId': None,
                    'pendingSession': None, 'answeredIds': []}
                history = json.dumps({'version': 1, 'currentSessionId': saved['id'], 'sessions': [saved]}, ensure_ascii=False)
                context.add_init_script(f"localStorage.setItem({json.dumps('medaxis.chat-history.v1:user:'+owner)}, {json.dumps(history)});")
            def bridge(route):
                path, query = urlsplit(route.request.url).path, urlsplit(route.request.url).query
                response = route.fetch(url=api+path+('?' + query if query else ''))
                lost = 'create_lost' if path == '/api/v1/consultations' else 'reply_lost' if path.endswith('/messages') and role == 'doctor' else None
                if route.request.method == 'POST' and lost and mode[lost] and response.ok:
                    mode[lost] = False
                    route.fulfill(status=500, json={'detail': '合成响应丢失，请重试'})
                else: route.fulfill(response=response)
            context.route('**/api/v1/**', bridge)
            page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            return context, page
        def auth(token): return {'Authorization': 'Bearer '+token}
        try:
            pc, patient = session(patient_token, 'patient')
            dc, doctor = session(doctor_token, 'doctor')
            patient.goto(web+'/chat')
            expect(patient.get_by_role('link', name='医生咨询', exact=True)).to_have_count(0)
            documents = []
            patient.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
            patient.get_by_role('button', name='转接真实医生', exact=True).click()
            dialog = patient.get_by_role('dialog', name='转接真实医生')
            expect(dialog.get_by_role('button', name='确认转接', exact=True)).to_be_disabled()
            dialog.get_by_role('combobox', name='选择医生', exact=True).click()
            patient.get_by_role('option', name='认证合成医生 · 合成医院 · 全科', exact=True).click()
            dialog.get_by_label('希望医生帮你解答什么？', exact=True).fill('合成资料复核问题')
            dialog.get_by_role('checkbox', name='共享的合成报告.png', exact=True).check()
            consent = dialog.get_by_role('checkbox', name='我同意向所选医生共享本次摘要及勾选的报告解析结果', exact=True)
            expect(dialog.get_by_role('button', name='确认转接', exact=True)).to_be_disabled()
            consent.check()
            dialog.get_by_role('button', name='确认转接', exact=True).click()
            expect(dialog.get_by_text('合成响应丢失，请重试', exact=True)).to_be_visible()
            expect(dialog.get_by_label('希望医生帮你解答什么？', exact=True)).to_have_value('合成资料复核问题')
            dialog.get_by_role('button', name='确认转接', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(patient.get_by_role('heading', name='咨询详情', exact=True)).to_be_visible()
            assert urlsplit(patient.url).path == '/chat' and not documents
            result = pc.request.get(api+'/api/v1/consultations', headers=auth(patient_token)).json()
            assert len(result['items']) == 1
            item_id = result['items'][0]['id']
            view = pc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(patient_token)).json()
            assert [m['filename'] for m in view['snapshot']['materials']] == ['共享的合成报告.png']
            stranger = pc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(os.environ['CONSULTATION_OTHER_TOKEN']))
            assert stranger.status == 404
            print('PASS: 明确勾选授权与报告；提交响应丢失保留草稿；重试只有一条咨询；其他医生无法访问', flush=True)
            doctor.goto(web+'/doctor')
            expect(doctor.get_by_role('button', name='收到新的患者咨询', exact=False)).to_be_visible()
            doctor.get_by_role('button', name='收到新的患者咨询', exact=False).click()
            expect(doctor.get_by_role('button', name='接受咨询', exact=True)).to_be_visible()
            doctor.get_by_text('查看共享资料 · 1 份报告', exact=True).click()
            expect(doctor.get_by_text('共享的合成报告.png', exact=True)).to_be_visible()
            expect(doctor.get_by_text('不共享的合成报告.png', exact=True)).to_have_count(0)
            doctor.get_by_role('button', name='接受咨询', exact=True).click()
            doctor.get_by_label('给患者的建议', exact=True).fill('合成专业回复，请补充资料')
            doctor.get_by_role('button', name='发布建议', exact=True).click()
            expect(doctor.get_by_text('合成响应丢失，请重试', exact=True)).to_be_visible()
            expect(doctor.get_by_label('给患者的建议', exact=True)).to_have_value('合成专业回复，请补充资料')
            doctor.get_by_role('button', name='发布建议', exact=True).click()
            expect(doctor.get_by_label('给患者的建议', exact=True)).to_have_value('')
            view = pc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(patient_token)).json()
            assert sum(m['kind'] == 'message' for m in view['messages']) == 1
            patient.reload()
            expect(patient.get_by_text('合成专业回复，请补充资料', exact=True)).to_be_visible()
            patient.get_by_label('补充说明', exact=True).fill('合成患者补充')
            patient.get_by_role('button', name='发送补充', exact=True).click()
            expect(patient.get_by_label('补充说明', exact=True)).to_have_value('')
            doctor.reload()
            expect(doctor.get_by_text('合成患者补充', exact=True)).to_be_visible()
            print('PASS: 站内通知进入待办；认证医生接单；回复持久化并去重；患者刷新恢复与补充；AI 原始摘要独立保留', flush=True)
            doctor.screenshot(path=str(ARTIFACT/'consultation-doctor-desktop.png'))
            patient.set_viewport_size({'width': 390, 'height': 844})
            patient.get_by_label('补充说明', exact=True).scroll_into_view_if_needed()
            assert patient.evaluate('document.documentElement.scrollWidth <= innerWidth')
            patient.screenshot(path=str(ARTIFACT/'consultation-patient-mobile.png'))
            # 外部状态变化后提交：草稿不丢，服务器拒绝旧版本。
            current = pc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(patient_token)).json()
            response = dc.request.post(api+'/api/v1/consultations/'+item_id+'/messages', headers=auth(doctor_token), data={
                'request_id': str(uuid4()), 'expected_revision': current['revision'], 'body': '并发合成医生建议', 'category': 'health_advice', 'next_state': 'awaiting_patient'})
            assert response.status == 200
            patient.get_by_label('补充说明', exact=True).fill('并发冲突保留的草稿')
            patient.get_by_role('button', name='发送补充', exact=True).click()
            expect(patient.get_by_text('咨询状态已变化，请刷新后重试；未发送内容仍保留', exact=True)).to_be_visible()
            expect(patient.get_by_label('补充说明', exact=True)).to_have_value('并发冲突保留的草稿')
            patient.get_by_role('button', name='发送补充', exact=True).click()
            expect(patient.get_by_label('补充说明', exact=True)).to_have_value('')
            patient.get_by_role('button', name='取消咨询与共享', exact=True).click()
            patient.get_by_role('button', name='确认取消', exact=True).click()
            expect(patient.get_by_role('button', name='取消咨询与共享', exact=True)).to_have_count(0)
            doctor.reload()
            expect(doctor.get_by_text('本次咨询已结束，共享授权已停止', exact=True)).to_be_visible()
            expect(doctor.get_by_text('合成患者补充', exact=True)).to_have_count(0)
            assert dc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(doctor_token)).status == 403
            assert pc.request.get(api+'/api/v1/consultations/'+item_id, headers=auth(patient_token)).status == 200
            patient.reload()
            expect(patient.get_by_text('并发冲突保留的草稿', exact=True)).to_be_visible()
            patient.set_viewport_size({'width': 320, 'height': 844})
            assert patient.evaluate('document.documentElement.scrollWidth <= innerWidth')
            patient.set_viewport_size({'width': 1440, 'height': 1000})
            def create_next(question):
                patient.get_by_role('button', name='重新转接', exact=True).click()
                form = patient.get_by_role('dialog', name='转接真实医生')
                form.get_by_role('combobox', name='选择医生', exact=True).click()
                patient.get_by_role('option', name='认证合成医生 · 合成医院 · 全科', exact=True).click()
                form.get_by_label('希望医生帮你解答什么？', exact=True).fill(question)
                form.get_by_role('checkbox', name='我同意向所选医生共享本次摘要及勾选的报告解析结果', exact=True).check()
                form.get_by_role('button', name='确认转接', exact=True).click()
                expect(form).to_have_count(0)
                doctor.reload()
                doctor.get_by_role('dialog', name='患者转接', exact=True).get_by_role('button', name='关闭', exact=True).click()
                doctor.get_by_role('button', name='查看咨询：浏览器合成问诊', exact=True).click()
                expect(doctor.get_by_role('button', name='接受咨询', exact=True)).to_be_visible()
            create_next('合成婉拒场景')
            doctor.get_by_role('button', name='婉拒', exact=True).click()
            expect(doctor.get_by_role('button', name='确认婉拒', exact=True)).to_be_disabled()
            doctor.get_by_label('婉拒原因', exact=True).fill('当前暂不能接诊（合成原因）')
            doctor.get_by_role('button', name='确认婉拒', exact=True).click()
            expect(doctor.get_by_text('本次咨询已结束，共享授权已停止。', exact=True)).to_be_visible()
            patient.reload()
            expect(patient.get_by_text('当前暂不能接诊（合成原因）', exact=True)).to_be_visible()
            create_next('合成完成场景')
            doctor.get_by_role('button', name='接受咨询', exact=True).click()
            doctor.get_by_label('给患者的建议', exact=True).fill('合成最终报告解读')
            doctor.get_by_role('combobox', name='建议类别', exact=False).click()
            doctor.get_by_role('option', name='报告解读', exact=True).click()
            doctor.get_by_role('combobox', name='回复后', exact=False).click()
            doctor.get_by_role('option', name='完成本次咨询', exact=True).click()
            mode['reply_lost'] = True
            doctor.get_by_role('button', name='发布建议', exact=True).click()
            expect(doctor.get_by_role('dialog', name='发布建议并完成咨询？')).to_be_visible()
            doctor.get_by_role('button', name='确认发布', exact=True).click()
            expect(doctor.get_by_label('给患者的建议', exact=True)).to_have_count(0)
            expect(doctor.get_by_text('合成最终报告解读', exact=True)).to_have_count(0)
            expect(doctor.get_by_text('合成完成场景', exact=True)).to_have_count(0)
            expect(doctor.get_by_role('dialog', name='发布建议并完成咨询？')).to_have_count(0)
            patient.reload()
            expect(patient.get_by_text('合成最终报告解读', exact=True)).to_be_visible()
            expect(patient.get_by_text('报告解读', exact=True)).to_be_visible()
            patient.get_by_role('dialog', name='医生接诊进度').get_by_role('button', name='关闭', exact=True).click()
            expect(patient.get_by_role('dialog', name='医生接诊进度')).to_have_count(0)
            assert urlsplit(patient.url).path == '/chat' and not urlsplit(patient.url).query
            expect(patient.get_by_label('问诊消息').get_by_text('合成 AI 原始摘要', exact=True)).to_be_visible()
            patient.get_by_role('button', name='转接真实医生', exact=True).click()
            expect(patient.get_by_text('合成最终报告解读', exact=True)).to_be_visible()
            assert not errors, errors
            print('PASS: 390px 手机无溢出；409 冲突草稿保留与重试；取消后医生 DOM 清空且 API 403；患者历史继续可读；无运行时错误', flush=True)
            print('PASS: 320px 无溢出；婉拒原因必填与患者可见；选择报告解读并确认完成后医生资料清空，患者保留最终建议', flush=True)
            print('PASS: 转接申请与回复均在 AI 问诊原地弹窗，无 document 请求；关闭回到原对话，再次打开恢复进度；医生现有工作台接诊', flush=True)
        except Exception:
            if 'doctor' in locals():
                doctor.screenshot(path=str(ARTIFACT/'consultation-browser-failure.png'))
                print('combobox-diagnostic:', doctor.get_by_role('combobox').evaluate_all("elements => elements.map(e => ({text: e.textContent, labelledBy: e.getAttribute('aria-labelledby')}))"), flush=True)
            raise
        finally:
            for context in contexts: context.close()
            browser.close()


if __name__ == '__main__':
    main()
