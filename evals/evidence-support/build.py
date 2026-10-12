"""冻结阶段7测试集；拒绝覆盖已有版本，不读取模型结果来选择金标。"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.ai/tasks/2026-10-09-evidence-support/frozen-v3'
OLD = [ROOT / '.ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json',
       ROOT / '.ai/tasks/2026-10-08-source-authority/validation-frozen-v1/dataset.json']
CORPUS = ROOT / '.ai/tasks/2026-10-07-rag-baseline/frozen-v1/corpus.json'
AUTHORITY = ROOT / '.ai/tasks/2026-10-08-source-authority/source-authority-manifest.json'
REVIEW = 'ai_draft_not_clinically_reviewed'

# 锚点和限定词均来自冻结原文。标签只评价给定摘录是否支持给定句子。
DEFINITIONS = [
    ('0a9e', '根据血清', '（2）代谢性', '儿童腹泻的等渗性脱水血钠范围是什么？',
     '这份儿童腹泻规范将等渗性脱水的血清钠范围列为130～150mmol/L。',
     '这份儿童腹泻规范将等渗性脱水的血清钠范围列为160～180mmol/L。',
     ['130～150mmol/L', '＜\n130mmol/L', '＞150mmol/L'],
     {'age_years': 3, 'condition': '急性感染性腹泻', 'purpose': '按本规范解释血钠分类'},
     {'age_years': 35, 'condition': '急性感染性腹泻', 'purpose': '直接断言本儿童规范适用于成人'},
     'not_applicable', '儿童规范不能直接作为成人适用性证据'),
    ('0a9e', '3.低钾血症', '4.低钙', '儿童腹泻规范是否允许含钾液直接静脉推注？',
     '该儿童腹泻规范要求含钾液缓慢静脉滴注，禁忌直接静脉推注，少尿、无尿者慎用。',
     '该儿童腹泻规范允许含钾液直接静脉推注，少尿、无尿者无需慎用。',
     ['禁\n忌直接静脉推注', '少尿、无尿者慎用', '有尿后\n补钾'],
     {'age_years': 4, 'condition': '腹泻并低钾', 'urine_present': True, 'purpose': '判断规范要求的补钾限制'},
     {'age_years': None, 'condition': None, 'urine_present': None, 'purpose': '给个人直接套用补钾安排'},
     'unknown', '缺年龄、病情、尿量，不能据此确认个人适用性'),
    ('5ce0', '1.1.5 Forehead', 'Subjective detection', 'NG143是否建议医护人员使用前额化学温度计？',
     'NG143认为前额化学温度计不可靠，医护人员不应使用。',
     'NG143认为前额化学温度计可靠，医护人员应优先使用。',
     ['Forehead chemical thermometers', 'unreliable', 'should not be used'],
     {'age_years': 2, 'actor': 'healthcare professional', 'device': 'forehead chemical thermometer', 'purpose': '发热评估测温'},
     {'age_years': 2, 'actor': 'healthcare professional', 'device': 'infrared tympanic thermometer', 'purpose': '将此段不可靠判断套用于耳温计'},
     'not_applicable', '前额化学温度计的判断不能扩展到耳温计'),
    ('5ce0', '1.2.13 Recognise', 'Fever in under 5s:', 'NG143中3至6个月婴儿39℃或更高属于何种严重疾病风险？',
     'NG143将3至6个月、体温39℃或更高的婴儿列入至少中等风险组。',
     'NG143将3至6个月、体温39℃或更高的婴儿列入低风险组。',
     ['3 to 6 months', '39° C or higher', 'at least an intermediate-risk'],
     {'age_months': 5, 'temperature_c': 39.2, 'purpose': '按此条判断最低风险组'},
     {'age_months': 48, 'temperature_c': 39.2, 'purpose': '直接套用3至6个月条款'},
     'not_applicable', '年龄条件不符；不能从此段推断4岁儿童的风险等级'),
    ('95b3', '扎那米韦（', '（2）RNA', '2025版流感方案如何限制哮喘患者使用吸入性扎那米韦？',
     '2025版流感方案不推荐哮喘或其他慢性呼吸道疾病患者使用吸入性扎那米韦。',
     '2025版流感方案推荐哮喘患者优先使用吸入性扎那米韦。',
     ['成人及 7 岁以上儿童', '不推荐哮喘', '不推荐扎那米韦吸\n入粉剂用雾化器'],
     {'age_years': 10, 'condition': '流感', 'asthma': False, 'purpose': '仅判断此段年龄及疾病限制是否满足'},
     {'age_years': 4, 'condition': '流感', 'asthma': False, 'purpose': '将本段年龄适用范围直接套用'},
     'not_applicable', '4岁不符合本段成人及7岁以上儿童范围'),
    ('95b3', '②法维拉韦', '（3）血凝素', '2025版流感方案中法维拉韦用于哪类成人流感及哪些前置条件？',
     '该方案将法维拉韦限于成人新型或再次流行的流感，且其他抗流感药物无效或效果不佳时使用，孕妇或可能怀孕者禁用。',
     '该方案推荐孕妇将法维拉韦作为普通流感的一线药，无需考虑其他药物效果。',
     ['成人新型或再次流行', '但仅限于其他抗流感病毒药物治疗无效或效果不佳', '孕\n妇或可能怀孕的妇女禁用'],
     {'age_years': 35, 'condition': '新型流感', 'other_antivirals_failed': True, 'pregnancy_possible': False, 'purpose': '核对本段必要适用条件，并非批准用药'},
     {'age_years': 35, 'condition': '流感', 'other_antivirals_failed': None, 'pregnancy_possible': None, 'purpose': '直接确认个人可按本段用药'},
     'unknown', '其他药物疗效与妊娠状态未知，不能确认满足条件'),
    ('eb49', '三、传播途径', '四、发病机制', '2025版儿童MPP指南的潜伏期多久，症状缓解后是否仍有传染性？',
     '该儿童MPP指南写明潜伏期1～3周，潜伏期内至症状缓解数周均有传染性。',
     '该儿童MPP指南写明潜伏期1～3天，症状缓解后立即失去传染性。',
     ['1～3 周', '症状缓解数周均有传染性', '飞沫和直接接触'],
     {'age_years': 8, 'condition': 'MPP', 'purpose': '解释指南中的一般传播范围，不确定个体是否仍排菌'},
     {'age_years': 8, 'condition': None, 'purpose': '把所有咳嗽都判为MP感染并按此段解释传染性'},
     'unknown', '未确定MP感染，不能把通用描述当成患者病原确诊'),
    ('eb49', '（四）可弯曲', '怀疑有黏液栓', '2025版儿童MPP指南是否推荐轻症常规做支气管镜介入？',
     '该儿童MPP指南要求避免过度使用支气管镜介入，轻症不推荐，并强调综合治疗。',
     '该儿童MPP指南推荐所有轻症常规做支气管镜介入，单一支气管镜足够。',
     ['避免过度使用，轻症不推荐', '综合治疗而非单一支', '而非必须支气管镜'],
     {'age_years': 8, 'condition': '轻症MPP', 'purpose': '核对本段对轻症常规介入的限制'},
     {'age_years': 8, 'condition': 'MPP，严重程度未知', 'purpose': '断言当前患儿属于轻症并无需支气管镜'},
     'unknown', '未确定轻重，通用轻症条款不能证明个体属于轻症'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != content:
            raise FileExistsError('已有内容不同，禁止覆盖：' + str(path))
        return
    path.write_text(content, encoding='utf-8')


def build():
    if OUT.exists():
        raise FileExistsError('已冻结，禁止覆盖；更改请建立新版本')
    corpus = read(CORPUS)
    old_sets = [read(p) for p in OLD]
    previous = [g for ds in old_sets for g in ds['gold_units']]
    authority = {d['document_id']: d for d in read(AUTHORITY)['documents']}
    units, specs = [], []
    for i, definition in enumerate(DEFINITIONS, 1):
        prefix, left, right, query, claim, false_claim, qualifiers, good, bad, label, reason = definition
        doc = next(d for d in corpus['documents'] if d['id'].startswith(prefix))
        text = doc['content']
        if text.count(left) != 1:
            raise ValueError('起始锚点必须唯一：' + left)
        start = text.index(left)
        end = text.index(right, start + len(left))
        raw = text[start:end]
        start += len(raw) - len(raw.lstrip())
        quote = raw.strip()
        end = start + len(quote)
        if not all(q in quote for q in qualifiers):
            raise ValueError('限定词须逐字存在于原文，不得使用转述：' + left)
        if any(g['document_id'] == doc['id'] and max(start, g['start']) < min(end, g['end']) for g in previous):
            raise ValueError('新原文与已暴露gold范围重叠')
        meta = authority[doc['id']]
        unit = {'id': f'E{i:02}', 'document_id': doc['id'], 'title': doc['title'],
                'document_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                'start': start, 'end': end, 'quote': quote, 'qualifiers': qualifiers,
                'metadata': {k: meta.get(k) for k in ['publisher', 'edition', 'published_date', 'verification_status']},
                'source_url': meta['new_source_url'], 'review_status': REVIEW}
        units.append(unit)
        specs.append((query, claim, false_claim, good, bad, label, reason))
    cases = []
    for i, (unit, spec) in enumerate(zip(units, specs)):
        query, claim, false_claim, good, bad, label, reason = spec
        # 每份文档的另一段：疾病/指南相同，但没有回答当前问题的具体要求。
        distractor = units[i + 1 if i % 2 == 0 else i - 1]
        pair_id = unit['id']
        base = {'topic_id': pair_id, 'query': query, 'required_edition': unit['metadata']['edition'],
                'review_status': REVIEW, 'split': 'frozen_validation_not_blind'}
        definitions = [
            ('Q+', 'query_specificity', unit['id'], None, None, 'answers', '原文明确回答该问题的具体要求'),
            ('Q-', 'query_specificity', distractor['id'], None, None, 'does_not_answer', '同份指南另一主题，不回答本题的具体要求'),
            ('S+', 'statement_support', unit['id'], claim, None, 'supported', '保留原文数值、否定及适用条件的转述'),
            ('S-', 'statement_support', unit['id'], false_claim, None, 'contradicted', '刻意改动数值、否定或条件，原文与该句相反'),
            ('A+', 'applicability', unit['id'], claim, good, 'applicable', '仅核对指定范围内必要条件，不批准诊疗安排'),
            ('A-', 'applicability', unit['id'], claim, bad, label, reason),
        ]
        for suffix, family, evidence_id, statement, context, expected, why in definitions:
            case = copy.deepcopy(base)
            case.update({'id': f'{pair_id}-{suffix}', 'pair_id': f'{pair_id}-{suffix[0]}',
                         'family': family, 'candidate_evidence_id': evidence_id,
                         'statement': statement, 'synthetic_context': context,
                         'expected_label': expected, 'rationale': why})
            cases.append(case)
    # 独立的版本反例：即使摘录完全相关，也不能用现有版次回答不存在于该摘录的新版要求。
    for i in (0, 2, 4, 6):
        unit = units[i]
        cases.append({'id': f"{unit['id']}-V", 'topic_id': unit['id'], 'pair_id': None,
                      'family': 'version_scope', 'query': f"请按2028版资料回答：{specs[i][0]}",
                      'required_edition': '2028年版', 'candidate_evidence_id': unit['id'],
                      'statement': None, 'synthetic_context': None, 'expected_label': 'version_mismatch',
                      'rationale': '冻结摘录及出处属于现有版次，不包含2028版更新证据',
                      'review_status': REVIEW, 'split': 'frozen_validation_not_blind'})
    # 正反例的展示编号仅留给审核者；执行编号取自输入内容，不能带 +/- 或预期标签。
    for case in cases:
        case['display_id'] = case['id']
        payload = {k: case[k] for k in ['family', 'query', 'required_edition', 'statement', 'synthetic_context', 'candidate_evidence_id']}
        case['id'] = 'T' + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]
    dataset = {'version': 'evidence-support-v3', 'scope': '给定问题/陈述/合成条件与原文片段的关系评测，不评价临床疗效',
               'not_blind': True, 'professional_reviewed': 0, 'gold_units': units, 'cases': cases}
    production = ['backend/app/services/rag.py', 'backend/app/services/knowledge_citations.py',
                  'backend/app/services/rag_context.py', 'backend/app/services/orchestrator.py']
    fingerprints = {p: sha(ROOT / p) for p in production}
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / 'corpus.json', {'documents': [{k: d[k] for k in ['id', 'title', 'content', 'text_sha256']} for d in corpus['documents']]})
    write(OUT / 'dataset.json', dataset)
    previous_asset = [{'name': p.parent.name, 'path': str(p.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(p),
                       'queries': [c['query'] for c in ds['cases']],
                       'ranges': [{k: g[k] for k in ['document_id', 'start', 'end']} for g in ds['gold_units']]}
                      for p, ds in zip(OLD, old_sets)]
    write(OUT / 'prior-exposure.json', previous_asset)
    manifest = {'version': 'evidence-support-v3', 'cases': len(cases), 'gold_units': len(units),
                'frozen_before_stage7_production_changes': True, 'stage7_production_changes': 0,
                'not_blind': True, 'source_corpus_shared': True, 'adjacent_chunk_sharing_possible': True,
                'professional_reviewed': 0, 'baseline_status': 'NOT_RUN',
                'source_assets': {'corpus_path': str(CORPUS.relative_to(ROOT)), 'corpus_sha256': sha(CORPUS),
                                  'authority_path': str(AUTHORITY.relative_to(ROOT)), 'authority_sha256': sha(AUTHORITY)},
                'production_sha256': fingerprints,
                'assets_sha256': {p: sha(OUT / p) for p in ['dataset.json', 'corpus.json', 'prior-exposure.json']}}
    # 给评测执行者的输入不含预期标签和gold解释，仍不声称盲测。
    inputs = [{k: c[k] for k in ['id', 'family', 'query', 'required_edition', 'statement', 'synthetic_context']} |
              {'candidate_source': next(u for u in units if u['id'] == c['candidate_evidence_id'])}
              for c in cases]
    for item in inputs:
        item['candidate_source'] = {k: v for k, v in item['candidate_source'].items() if k not in ['qualifiers', 'review_status']}
    inputs.sort(key=lambda item: item['id'])
    write(OUT / 'inputs.json', {'version': dataset['version'], 'cases': inputs})
    lines = ['# 阶段7固定测试题（AI草稿，非盲测，待专业审核）', '',
             '| ID | 检查项 | 问题或陈述 | 预期 |', '|---|---|---|---|']
    lines += [f"| {c['display_id']} ({c['id']}) | {c['family']} | {c['statement'] or c['query']} | {c['expected_label']} |" for c in cases]
    (OUT / 'QUESTIONS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (OUT / 'review.csv').write_text('id,reviewer,reviewed_label,decision,comment\n' +
                                  '\n'.join(c['id'] + ',,,,' for c in cases) + '\n', encoding='utf-8')
    for name in ['inputs.json', 'QUESTIONS.md', 'review.csv']:
        manifest['assets_sha256'][name] = sha(OUT / name)
    write(OUT / 'manifest.json', manifest)
    print(json.dumps({'output': str(OUT), 'cases': len(cases), 'units': len(units), 'baseline': 'NOT_RUN'}, ensure_ascii=False))


if __name__ == '__main__':
    build()
