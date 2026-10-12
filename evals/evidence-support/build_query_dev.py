"""冻结独立于旧题原文范围的开发样本；同语料、非盲测，不是临床验收集。"""
import hashlib
import json
from pathlib import Path

from revise_v4 import identity
from verify import DEFAULT, ROOT, digest, load, require, validate

PARENT = DEFAULT.with_name('frozen-v4')
OUT = DEFAULT.with_name('query-development-v2')
OLD = [ROOT / '.ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json',
       ROOT / '.ai/tasks/2026-10-08-source-authority/validation-frozen-v1/dataset.json',
       PARENT / 'dataset.json']
# 每对是同份文档的两种用途；原文坐标已定，标签不根据生产输出选择。
SPECS = [
    ('0a9e', 1117, 1182, '儿童腹泻规范中，哪些大便表现需要粪便细菌培养，哪类急性水样便患儿无需常规培养？请两部分都回答。',
     ['应行粪便细菌培养', '免疫功能正常患\n儿无需常规行粪便培养'], '出现急性水样便'),
    ('0a9e', 2640, 2713, '请列出儿童腹泻入院标准提到的脱水程度、休克及消化道外器官或系统受累情况，不能只回答脱水。',
     ['中重度脱水', '休克', '消化\n道外器官或系统受累'], '电解质紊乱'),
    ('95b3', 2078, 2139, '按流感方案，核酸检测可采集哪些标本，且能否区分病毒类型和亚型？请同时回答。',
     ['鼻咽拭子、咽拭子、气管抽取物、痰或肺\n泡灌洗液', '能区分病毒类\n型和亚型'], '敏感性和特异性'),
    ('95b3', 2518, 2629, '流感临床诊断病例的流行病学史涉及发病前多久，是否还需排除其他引起流感样症状的疾病？请同时回答。',
     ['发病前 7 天内', '且排除其他引起流感样症状的疾病'], '且排除'),
    ('5ce0', 12138, 12541, 'NG143将儿童心动过速放在哪个最低风险层级，表1对2至5岁儿童给出的心率阈值是多少？请两项都回答。',
     ['at least an intermediate-risk', '2 to 5 years More than 140'], 'Table 1 Advanced'),
    ('5ce0', 13268, 13567, '按NG143，发热伴non-blanching rash应考虑何种疾病，列出的皮损直径及毛细血管再充盈时间数值条件各是什么？',
     ['meningococcal disease', 'larger than 2 mm', '3 seconds or longer'], '• an ill-looking child'),
    ('eb49', 6473, 7074, '儿童MPP重症判定原文中的静息海平面吸空气氧饱和度阈值，以及24至48小时影像进展比例阈值分别是什么？请同时保留测量条件。',
     ['静息状态下，海平面吸空气时指脉氧饱和度≤0.93', '24-48h 进\n展超过 50%'], '5.影像学表现'),
    ('eb49', 7125, 7341, '儿童MPP早期预警原文中，治疗后持续高热多久算一项指标，是否还列出基础疾病和抗肺炎支原体药物治疗延迟？请回答三项。',
     ['治疗后 72h 持续高热不退', '存在基础疾病', '药物治疗延迟'], '（二）病情'),
]


def build_data(corpus, parent):
    units = []
    for i, (prefix, start, end, query, requirements, cut) in enumerate(SPECS, 1):
        doc = next(d for d in corpus['documents'] if d['id'].startswith(prefix))
        raw = doc['content'][start:end]
        start += len(raw) - len(raw.lstrip())
        quote = raw.strip()
        end = start + len(quote)
        source = next(u for u in parent['gold_units'] if u['document_id'] == doc['id'])
        require(all(q in quote for q in requirements), '完整候选缺限定词')
        full = {'id': f'D{i:02}', 'document_id': doc['id'], 'title': doc['title'],
                'document_sha256': doc['text_sha256'], 'start': start, 'end': end, 'quote': quote,
                'qualifiers': requirements, 'metadata': source['metadata'], 'source_url': source['source_url'],
                'review_status': 'ai_draft_not_clinically_reviewed'}
        partial_quote = quote[:quote.index(cut)].rstrip()
        kept = [q for q in requirements if q in partial_quote]
        require(0 < len(kept) < len(requirements), '部分候选必须回答部分且缺部分要求')
        partial = {**full, 'id': f'D{i:02}P', 'end': start + len(partial_quote),
                   'quote': partial_quote, 'qualifiers': kept}
        units.extend([full, partial])
    by_id = {u['id']: u for u in units}
    cases = []
    for i, spec in enumerate(SPECS, 1):
        full = by_id[f'D{i:02}']
        distractor = by_id[f'D{i + 1 if i % 2 else i - 1:02}']
        query, requirements = spec[3], spec[4]
        require(not any(q in distractor['quote'] for q in requirements), '邻近主题包含请求要点，需重新审核')
        for suffix, source, label, reason in [
            ('complete', full, 'answers', '给定摘录覆盖问题明列的所有要求'),
            ('partial', by_id[f'D{i:02}P'], 'partial_answer', '原文前缀有用但遗漏部分请求，不能声称完整回答，也不应直接视作无关'),
            ('other', distractor, 'does_not_answer', '同份指南的另一用途，不回答本题请求要点'),
        ]:
            case = {'id': '', 'display_id': f'D{i:02}-{suffix}', 'topic_id': full['id'],
                    'pair_id': f'D{i:02}-Q' if suffix != 'partial' else None,
                    'family': 'query_specificity', 'query': query, 'required_edition': full['metadata']['edition'],
                    'statement': None, 'synthetic_context': None, 'candidate_evidence_id': source['id'],
                    'expected_label': label, 'rationale': reason, 'request_requirements': requirements,
                    'covered_requirements': [q for q in requirements if q in source['quote']],
                    'missing_requirements': [q for q in requirements if q not in source['quote']],
                    'review_status': 'ai_draft_not_clinically_reviewed', 'split': 'development_non_blind'}
            case['id'] = identity(case)
            cases.append(case)
    # 不能让完整/部分候选编号携带P等答案提示；来源ID只由文档指纹和坐标派生。
    opaque = {}
    for unit in units:
        payload = [unit['document_sha256'], unit['start'], unit['end']]
        opaque[unit['id']] = 'U' + hashlib.sha256(json.dumps(payload).encode('utf-8')).hexdigest()[:16]
    for case in cases:
        case['topic_id'] = opaque[case['topic_id']]
        case['candidate_evidence_id'] = opaque[case['candidate_evidence_id']]
        case['id'] = identity(case)
    for unit in units:
        unit['id'] = opaque[unit['id']]
    return {'version': 'query-development-v2', 'scope': '给定候选的请求完整性开发集；部分回答不是无关资料，不用于个人诊疗',
            'not_blind': True, 'professional_reviewed': 0, 'gold_units': units, 'cases': cases}


def verify_contract(folder=OUT):
    validate(folder)
    parent = load(PARENT / 'dataset.json')
    corpus = load(folder / 'corpus.json')
    data = load(folder / 'dataset.json')
    require(data == build_data(corpus, parent), '开发集不符合固定采样/标签合同')
    manifest = load(folder / 'manifest.json')
    require(manifest['parent_dataset_sha256'] == digest(PARENT / 'dataset.json'), 'v4父题库变化')
    require(digest(folder / 'corpus.json') == digest(PARENT / 'corpus.json'), '语料变化')
    expected = [{'name': str(p.parent), 'path': str(p.relative_to(ROOT)), 'sha256': digest(p),
                 'queries': [c['query'] for c in load(p)['cases']],
                 'ranges': [{k: u[k] for k in ['document_id', 'start', 'end']} for u in load(p)['gold_units']]} for p in OLD]
    require(load(folder / 'prior-exposure.json') == expected, '旧题排除范围/查询不完整')
    return {'status': 'PASS_DEVELOPMENT_ASSETS_ONLY', 'cases': 24, 'topics': 8, 'source_spans': 16,
            'complete': 8, 'partial': 8, 'other_topic': 8, 'old_span_overlap': 0, 'old_query_reuse': 0,
            'corpus_shared': True, 'not_blind': True, 'clinical_approval': False,
            'opaque_candidate_ids': True}


def build():
    require(not OUT.exists(), '开发集已冻结，禁止覆盖')
    validate(PARENT, check_production=True)
    parent = load(PARENT / 'dataset.json')
    corpus = load(PARENT / 'corpus.json')
    data = build_data(corpus, parent)
    # 写入前确认范围与题目没有复用三套旧gold；保留真实来源，不需要新入库。
    previous = []
    for path in OLD:
        old = load(path)
        ranges = [{k: u[k] for k in ['document_id', 'start', 'end']} for u in old['gold_units']]
        for unit in data['gold_units']:
            require(not any(g['document_id'] == unit['document_id'] and max(g['start'], unit['start']) < min(g['end'], unit['end']) for g in ranges), '旧gold范围重叠')
        previous.append({'name': str(path.parent), 'path': str(path.relative_to(ROOT)), 'sha256': digest(path),
                         'queries': [c['query'] for c in old['cases']], 'ranges': ranges})
    OUT.mkdir()
    def write(name, value):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'corpus.json').write_bytes((PARENT / 'corpus.json').read_bytes())
    write('dataset.json', data)
    write('prior-exposure.json', previous)
    lookup = {u['id']: u for u in data['gold_units']}
    inputs = []
    for c in data['cases']:
        item = {k: c[k] for k in ['id', 'family', 'query', 'required_edition', 'statement', 'synthetic_context']}
        item['candidate_source'] = {k: v for k, v in lookup[c['candidate_evidence_id']].items() if k not in ['qualifiers', 'review_status']}
        inputs.append(item)
    write('inputs.json', {'version': data['version'], 'cases': sorted(inputs, key=lambda c: c['id'])})
    lines = ['# 请求完整性开发集（24条，AI草稿，非盲测）', '',
             '此集与旧题原文范围/问题不重叠，但共享4份语料。partial_answer表示有用但不完整，不应直接删除。', '']
    for c in data['cases']:
        source = lookup[c['candidate_evidence_id']]
        lines.extend([f"## {c['display_id']} / {c['id']}", '', f"问题：{c['query']}", '',
                      f"候选原文（{source['title']}，字符{source['start']}至{source['end']}，end不含）：", '',
                      '```text', source['quote'], '```', '', f"预期：{c['expected_label']}；{c['rationale']}", '',
                      f"缺少的请求要点：{json.dumps(c['missing_requirements'], ensure_ascii=False)}", '',
                      f"官方出处：{source['source_url']}", ''])
    (OUT / 'QUESTIONS.md').write_text('\n'.join(lines), encoding='utf-8')
    (OUT / 'review.csv').write_text('id,reviewer,reviewed_label,decision,comment\n' + '\n'.join(c['id'] + ',,,,' for c in data['cases']) + '\n', encoding='utf-8')
    manifest = {'version': data['version'], 'cases': 24, 'gold_units': 16, 'baseline_status': 'NOT_RUN',
                'parent_version': parent['version'], 'parent_dataset_sha256': digest(PARENT / 'dataset.json'),
                'production_sha256': load(PARENT / 'manifest.json')['production_sha256'],
                'not_blind': True, 'source_corpus_shared': True, 'professional_reviewed': 0,
                'clinical_approval': False, 'sampling_fixed_before_production_baseline': True,
                'assets_sha256': {n: digest(OUT / n) for n in ['dataset.json','corpus.json','prior-exposure.json','inputs.json','QUESTIONS.md','review.csv']}}
    write('manifest.json', manifest)
    print(json.dumps(verify_contract(), ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify_contract(), ensure_ascii=False))
    else:
        build()
