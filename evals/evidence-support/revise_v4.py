"""按外部意见复核生成派生v4，保持v3/原审核/基线不变。"""
import copy
import hashlib
import json
from pathlib import Path

from verify import DEFAULT, ROOT, digest, load, require, validate

OUT = DEFAULT.with_name('frozen-v4')
REVIEW = DEFAULT.parent / 'deepseek-review-v1'
FIELDS = ['family', 'query', 'required_edition', 'statement', 'synthetic_context', 'candidate_evidence_id']


def identity(case):
    payload = {k: case[k] for k in FIELDS}
    return 'T' + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def revise(old):
    data = copy.deepcopy(old)
    data['version'] = 'evidence-support-v4'
    changes = {
        'E05-A+': ('标签修订：缺少其他慢性呼吸道疾病状态，保留未知而不补造事实',
                   'expected_label,rationale,display_id'),
        'E06-A+': ('限定评测条款，排除未核对的哺乳/剂量等条件，不能解释为批准用药', 'synthetic_context,rationale'),
        'E04-A+': ('最低风险组改成是否至少中等风险组', 'synthetic_context'),
        'E05-V': ('明确请求2028版，去掉请求问题中的2025版', 'query'),
        'E07-V': ('明确请求2028版，去掉请求问题中的2025版', 'query'),
    }
    mapping = []
    for previous, case in zip(old['cases'], data['cases']):
        display = previous['display_id']
        if display == 'E05-A+':
            case.update(expected_label='unknown', display_id='E05-A-unknown',
                        rationale='原文同时限制哮喘或其他慢性呼吸道疾病；仅排除哮喘，另一项状态未知')
        elif display == 'E06-A+':
            case['synthetic_context']['purpose'] = (
                '仅核对成人、新型或再次流行流感、其他抗流感药无效或效果不佳、非妊娠这四项条款；'
                '不评价哺乳条件、剂量或其他个人用药条件，也不批准用药')
            case['rationale'] = '给定条件满足明列的四项条款；该标签不确认哺乳条件或个人完整用药适用性'
        elif display == 'E04-A+':
            case['synthetic_context']['purpose'] = '按此条判断是否至少中等风险组'
        elif display == 'E05-V':
            case['query'] = '请按2028版资料回答：流感方案如何限制哮喘患者使用吸入性扎那米韦？'
        elif display == 'E07-V':
            case['query'] = '请按2028版资料回答：儿童MPP指南的潜伏期多久，症状缓解后是否仍有传染性？'
        case['id'] = identity(case)
        mapping.append({'old_id': previous['id'], 'new_id': case['id'],
                        'old_display_id': display, 'new_display_id': case['display_id'],
                        'old_label': previous['expected_label'], 'new_label': case['expected_label'],
                        'kind': 'revised' if display in changes else 'unchanged',
                        'input_changed': previous['id'] != case['id'],
                        'reason': changes.get(display, ('原样继承v3', ''))[0]})
    complete = copy.deepcopy(next(c for c in data['cases'] if c['display_id'] == 'E05-A-unknown'))
    complete.update(display_id='E05-A-complete', pair_id=None, expected_label='applicable',
                    rationale='仅核对原文年龄及疾病限制：年龄符合且两类疾病状态均已明确排除；不批准用药')
    complete['synthetic_context']['other_chronic_resp_disease'] = False
    complete['id'] = identity(complete)
    data['cases'].append(complete)
    mapping.append({'old_id': None, 'new_id': complete['id'], 'old_display_id': None,
                    'new_display_id': complete['display_id'], 'old_label': None,
                    'new_label': 'applicable', 'kind': 'added', 'input_changed': True,
                    'reason': '保留信息不足案例，同时新增年龄/疾病条件明确的正例；独立附加例不冒充新对照组'})
    return data, mapping


def build():
    require(not OUT.exists(), 'v4已存在，禁止覆盖冻结资产')
    validate(DEFAULT, check_production=True)
    decisions = load(REVIEW / 'decisions.json')
    require(digest(DEFAULT / 'dataset.json') == decisions['dataset_sha256'], '被审核题库变化')
    report = DEFAULT / 'MedAxis 评测数据集独立审核报告.md'
    require(digest(report) == decisions['report_sha256'], '审核报告变化')
    old = load(DEFAULT / 'dataset.json')
    data, mapping = revise(old)
    OUT.mkdir()
    def write(name, value):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write('dataset.json', data)
    for name in ['corpus.json', 'prior-exposure.json']:
        (OUT / name).write_bytes((DEFAULT / name).read_bytes())
    units = {u['id']: u for u in data['gold_units']}
    inputs = []
    for case in data['cases']:
        item = {k: case[k] for k in ['id', 'family', 'query', 'required_edition', 'statement', 'synthetic_context']}
        item['candidate_source'] = {k: v for k, v in units[case['candidate_evidence_id']].items()
                                    if k not in ['qualifiers', 'review_status']}
        inputs.append(item)
    write('inputs.json', {'version': data['version'], 'cases': sorted(inputs, key=lambda c: c['id'])})
    write('revision-map.json', {'parent_version': old['version'], 'version': data['version'], 'rows': mapping})
    lines = ['# v4测试题（派生AI草稿，非盲测，专业审核0题）', '',
             '包含原52题的5条修订及1条新增。此版不是独立开发集。条件与用途单独展示，避免只读陈述误解适用性。', '',
             '| 展示编号 / 执行ID | 检查项 | 问题或陈述 | 条件与用途 | 预期 |', '|---|---|---|---|---|']
    for c in data['cases']:
        context = json.dumps(c['synthetic_context'], ensure_ascii=False) if c['synthetic_context'] else '—'
        lines.append(f"| {c['display_id']} / {c['id']} | {c['family']} | {c['statement'] or c['query']} | {context} | {c['expected_label']} |")
    (OUT / 'QUESTIONS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (OUT / 'review.csv').write_text('id,reviewer,reviewed_label,decision,comment\n' +
                                  '\n'.join(c['id'] + ',,,,' for c in data['cases']) + '\n', encoding='utf-8')
    write('review-provenance.json', {
        'report_path': str(report.relative_to(ROOT)), 'report_sha256': digest(report),
        'decisions_sha256': digest(REVIEW / 'decisions.json'), 'professional_reviewed': 0,
        'meaning': '用户提供的另一份AI审核及主代理证据复核，不是医学审核；新条款和新增正例未再次外审',
    })
    manifest = copy.deepcopy(load(DEFAULT / 'manifest.json'))
    manifest.update(version=data['version'], cases=len(data['cases']), baseline_status='NOT_RUN',
                    parent_dataset_sha256=digest(DEFAULT / 'dataset.json'), parent_inputs_sha256=digest(DEFAULT / 'inputs.json'),
                    parent_manifest_sha256=digest(DEFAULT / 'manifest.json'), parent_version=old['version'],
                    revised_cases=5, added_cases=1, independent_development_set=False)
    names = ['dataset.json', 'corpus.json', 'prior-exposure.json', 'inputs.json', 'QUESTIONS.md',
             'review.csv', 'revision-map.json', 'review-provenance.json']
    manifest['assets_sha256'] = {name: digest(OUT / name) for name in names}
    write('manifest.json', manifest)
    print(json.dumps(validate(OUT, check_production=True), ensure_ascii=False))


def verify_revision(data=None, mapping=None):
    validate(OUT)
    manifest = load(OUT / 'manifest.json')
    require(manifest['parent_dataset_sha256'] == digest(DEFAULT / 'dataset.json'), '父题库指纹变化')
    require(manifest['parent_inputs_sha256'] == digest(DEFAULT / 'inputs.json'), '父输入指纹变化')
    require(manifest['parent_manifest_sha256'] == digest(DEFAULT / 'manifest.json'), '父manifest变化')
    expected_data, expected_mapping = revise(load(DEFAULT / 'dataset.json'))
    actual_data = data if data is not None else load(OUT / 'dataset.json')
    actual_mapping = mapping if mapping is not None else load(OUT / 'revision-map.json')['rows']
    require(actual_data == expected_data, '新版题库不符合审核修订合同')
    require(actual_mapping == expected_mapping, '修订映射不符合实际题目变化')
    provenance = load(OUT / 'review-provenance.json')
    require(provenance['report_sha256'] == digest(DEFAULT / 'MedAxis 评测数据集独立审核报告.md'), '审核报告变化')
    require(provenance['decisions_sha256'] == digest(REVIEW / 'decisions.json'), '复核处置变化')
    return {'status': 'PASS_REVISION_CONTRACT_ONLY', 'cases': 53, 'unchanged': 47,
            'revised': 5, 'added': 1, 'clinical_approval': False,
            'parent_assets_unchanged': True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify_revision(), ensure_ascii=False))
    else:
        build()
