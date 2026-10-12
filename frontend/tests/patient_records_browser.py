"""问诊记录展示回归；仅使用合成数据与模拟 API。"""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from chat_history_browser import BASE, MockAPI, token
from report_reading_browser import assert_summary_order


REPORT = {
    'primary_diagnosis': '腹部不适，原因待进一步评估',
    'severity': 'moderate',
    'confidence': 'low',
    'key_findings': [
        '腹部不适持续 3 天，餐后较明显。',
        '每日腹泻 3 次，伴轻微腹胀。',
        '自测体温 37.2°C，未报告呕吐。',
        '近期饮食有变化，具体诱因仍需确认。[S1]',
        '既往用药情况需要进一步补充。',
    ],
    'recommended_actions': [
        '与接诊医生说明症状持续时间及变化。',
        '记录排便次数、饮食和体温变化。',
        '携带既往检查资料，便于医生对照。',
        '不要自行调整原有处方药，先咨询医生。',
        '如症状持续或加重，及时复诊。',
    ],
    'recommended_tests': ['血常规', '便常规', '电解质', '其他检查由医生评估是否需要'],
    'follow_up_timeline': '若不适持续，及时就诊；带上症状记录及已有检查资料。',
    'red_flags': ['如出现持续剧烈腹痛、便血或明显脱水，请及时就医。'],
    'contraindications': [f'注意事项 {index}：具体用药与饮食限制请由医生确认。' for index in range(1, 6)],
    'differential_diagnoses': [{'diagnosis': '其他可能原因', 'reasoning': '需要结合检查进一步评估。'}],
    'knowledge_citations': [{
        'citation_id': 'S1', 'source_type': 'internal', 'title': '合成参考资料',
        'excerpt': '仅供界面验证的合成引文，不是医疗依据。',
        'document_id': 'synthetic-doc', 'chunk_id': 'synthetic-chunk', 'chunk_index': 0,
    }],
}

CASES = [
    {'id': 'demo-case-a', 'title': '餐后腹部不适与腹泻', 'chief_complaint': '餐后腹部不适与腹泻',
     'description': '持续 3 天，餐后明显，伴轻微腹胀', 'status': 'pending_review', 'created_at': '2026-09-29T08:30:00Z'},
    {'id': 'empty-case', 'title': '皮肤瘙痒记录', 'description': '暂无总结', 'status': 'pending_review', 'created_at': '2026-09-25T06:00:00Z'},
    {'id': 'demo-case-b', 'title': '病例 B · 失败切换', 'description': '', 'status': 'pending_review', 'created_at': '2026-09-20T00:00:00Z'},
]


class RecordsAPI(MockAPI):
    def route(self, route):
        path = route.request.url.split('?')[0]
        if path.endswith('/patient/cases'):
            data = CASES
        elif path.endswith('/patient/cases/demo-case-a/recovery'):
            data = {'case': CASES[0], 'report': REPORT, 'materials': [], 'lab_reports': []}
        elif path.endswith('/patient/cases/empty-case/recovery'):
            data = {'case': CASES[1], 'report': None, 'materials': [], 'lab_reports': []}
        else:
            return super().route(route)
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))


def main():
    artifact = Path(os.getenv('REPORT_SCREENSHOT_DIR', str(Path(__file__).resolve().parents[2] / '.ai/tasks/2026-09-30-records-redesign')))
    artifact.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL', 'msedge'), headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/api/v1/**', RecordsAPI().route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.evaluate('jwt => { localStorage.setItem("access_token", jwt); localStorage.setItem("user_role", "patient"); }', token('records-ux'))
            page.goto(f'{BASE}/cases')
            page.wait_for_load_state('networkidle')
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_be_visible()
            expect(page.get_by_text('不是确诊', exact=False)).to_be_visible()
            assert_summary_order(page)
            expect(page.get_by_text('一眼看重点', exact=True)).to_have_count(0)
            expect(page.get_by_text(REPORT['red_flags'][0], exact=True)).to_be_visible()
            for precaution in REPORT['contraindications']:
                expect(page.get_by_text(precaution, exact=True)).to_be_visible()
            expect(page.get_by_text(REPORT['recommended_actions'][3], exact=True)).not_to_be_visible()
            page.wait_for_function("() => document.getAnimations().filter(animation => animation.animationName === 'casesFadeIn').every(animation => animation.playState === 'finished')")
            page.screenshot(path=str(artifact / 'records-desktop.png'), full_page=True)
            page.get_by_role('button', name='展开全部建议（5 项）', exact=True).click()
            expect(page.get_by_text(REPORT['recommended_actions'][3], exact=True)).to_be_visible()
            page.get_by_role('button', name='收起建议', exact=True).click()
            expect(page.get_by_text(REPORT['recommended_actions'][3], exact=True)).not_to_be_visible()
            page.get_by_role('button', name='展开全部症状要点（5 项）', exact=True).click()
            page.get_by_role('link', name='引用 S1，查看来源', exact=True).click()
            expect(page.get_by_text('合成参考资料', exact=True)).to_be_visible()
            page.get_by_role('button', name='参考资料').click()
            page.get_by_role('button', name='收起症状要点', exact=True).click()
            page.get_by_role('button', name='展开全部检查建议（4 项）', exact=True).click()
            expect(page.get_by_text(REPORT['recommended_tests'][3], exact=True)).to_be_visible()
            page.get_by_role('button', name='收起检查建议', exact=True).click()
            page.emulate_media(media='print')
            expect(page.get_by_text(REPORT['recommended_actions'][4], exact=True)).to_be_visible()
            expect(page.get_by_text(REPORT['key_findings'][4], exact=True)).to_be_visible()
            page.emulate_media(media='screen')
            page.get_by_role('button', name='皮肤瘙痒记录', exact=False).click()
            expect(page.get_by_text('这次问诊还没有总结。', exact=True)).to_be_visible()
            page.get_by_role('button', name='病例 B · 失败切换', exact=False).click()
            expect(page.get_by_role('alert')).to_contain_text('这条问诊记录暂时无法读取')
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_have_count(0)
            print('PASS: 重点分区、完整风险提示、逐组展开、引用跳转、打印条目与失败切换')

            for width in (390, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(f'{BASE}/cases?case_id=demo-case-a')
                expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_be_visible()
                assert_summary_order(page)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), width
                page.wait_for_function("() => document.getAnimations().filter(animation => animation.animationName === 'casesFadeIn').every(animation => animation.playState === 'finished')")
                page.screenshot(path=str(artifact / f'records-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.get_by_role('button', name='返回问诊记录', exact=True).click()
            expect(page.get_by_role('heading', name='问诊记录', exact=True)).to_be_visible()
            page.get_by_role('button', name='餐后腹部不适与腹泻', exact=False).click()
            expect(page.get_by_text(REPORT['primary_diagnosis'], exact=True)).to_be_visible()
            page.get_by_role('button', name='展开全部建议（5 项）', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.get_by_text(REPORT['recommended_actions'][4], exact=True)).to_be_visible()
            assert not errors, errors
            print('PASS: 手机、平板与桌面无横向溢出；手机返回/重选与键盘展开；无运行时异常')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
