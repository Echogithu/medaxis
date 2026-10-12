"""测试资产校验，不将校验通过当作生产检索或医疗评测通过。"""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / '.ai/tasks/2026-10-09-evidence-support/frozen-v3'
LABELS = {
    'query_specificity': {'answers', 'partial_answer', 'does_not_answer'},
    'statement_support': {'supported', 'contradicted', 'insufficient'},
    'applicability': {'applicable', 'not_applicable', 'unknown'},
    'version_scope': {'version_match', 'version_mismatch', 'unknown'},
}
VERSION_COUNTS = {'evidence-support-v3': 52, 'evidence-support-v4': 53, 'query-development-v1': 24, 'query-development-v2': 24}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(folder=DEFAULT, check_production=False):
    manifest = load(folder / 'manifest.json')
    for name, expected in manifest['assets_sha256'].items():
        require(Path(name).name == name, '资产名必须是当前目录普通文件名')
        require(digest(folder / name) == expected, '冻结指纹不符：' + name)
    dataset, corpus, previous, inputs = [load(folder / p) for p in
                                        ['dataset.json', 'corpus.json', 'prior-exposure.json', 'inputs.json']]
    documents = {d['id']: d for d in corpus['documents']}
    units = {g['id']: g for g in dataset['gold_units']}
    cases = dataset['cases']
    require(len(documents) == len(corpus['documents']) == 4, '文档ID重复或数量错误')
    unit_count = 16 if dataset['version'].startswith('query-development-') else 8
    require(len(units) == len(dataset['gold_units']) == manifest['gold_units'] == unit_count, 'gold数量或ID错误')
    require(dataset['version'] == manifest['version'] == inputs['version'], '资产版本不一致')
    require(dataset['version'] in VERSION_COUNTS, '未知冻结版本')
    require(len(cases) == manifest['cases'] == VERSION_COUNTS[dataset['version']], '测试题数量错误')
    require(dataset['professional_reviewed'] == 0 and dataset['not_blind'] is True, '审核或盲测声明错误')
    old_ranges = [g for p in previous for g in p['ranges']]
    old_queries = {''.join(q.lower().split()) for p in previous for q in p['queries']}
    for doc in documents.values():
        require(hashlib.sha256(doc['content'].encode('utf-8')).hexdigest() == doc['text_sha256'], '语料文本SHA不符')
    for unit in units.values():
        doc = documents[unit['document_id']]
        require(unit['document_sha256'] == doc['text_sha256'], 'gold文档SHA不符')
        require(0 <= unit['start'] < unit['end'] <= len(doc['content']), '原文范围无效')
        require(doc['content'][unit['start']:unit['end']] == unit['quote'], '原文摘录与位置不一致')
        require(unit['qualifiers'] and all(q in unit['quote'] for q in unit['qualifiers']), '限定词不存在于原文')
        require(unit['source_url'].startswith('https://') and unit['metadata']['edition'], '缺官方出处或版次')
        require(not any(g['document_id'] == unit['document_id'] and
                        max(g['start'], unit['start']) < min(g['end'], unit['end']) for g in old_ranges), '新旧gold重叠')
    ids, pairs = set(), {}
    for case in cases:
        require(case['id'] not in ids, '测试ID重复')
        require(len(case['id']) == 17 and case['id'][0] == 'T' and all(c in '0123456789abcdef' for c in case['id'][1:]), '执行ID泄漏正反标签或格式无效')
        ids.add(case['id'])
        require(case['candidate_evidence_id'] in units, '候选原文不存在')
        require(case['topic_id'] in units, '题目原文不存在')
        require(case['expected_label'] in LABELS[case['family']], '预期标签无效')
        require(case['expected_label'] != 'partial_answer' or dataset['version'].startswith('query-development-'), '部分回答金标仅适用于开发集合同')
        require(case['review_status'] == 'ai_draft_not_clinically_reviewed', '审核状态不能虚报')
        require(''.join(case['query'].lower().split()) not in old_queries, '题目复用旧集')
        if case['family'] == 'statement_support':
            require(bool(case['statement']), '陈述支持题必须有陈述')
        if case['family'] == 'applicability':
            require(bool(case['synthetic_context']), '适用性题必须有合成条件')
        if case['family'] == 'query_specificity':
            expected_id = case['topic_id'] if case['expected_label'] == 'answers' else None
            require((case['candidate_evidence_id'] == case['topic_id']) == bool(expected_id), '问题正反例原文关系不符')
        if case['pair_id']:
            pairs.setdefault(case['pair_id'], []).append(case)
    for pair in pairs.values():
        require(len(pair) == 2 and pair[0]['expected_label'] != pair[1]['expected_label'], '正反对照缺失')
    expected_inputs = []
    for case in cases:
        item = {k: case[k] for k in ['id', 'family', 'query', 'required_edition', 'statement', 'synthetic_context']}
        item['candidate_source'] = {k: v for k, v in units[case['candidate_evidence_id']].items()
                                    if k not in ['qualifiers', 'review_status']}
        expected_inputs.append(item)
    expected_inputs.sort(key=lambda item: item['id'])
    require(inputs['cases'] == expected_inputs, '执行输入与冻结题不一致或包含预期标签')
    if check_production:
        for name, expected in manifest['production_sha256'].items():
            require(digest(ROOT / name) == expected, '生产源码已变化，先记录新运行版本：' + name)
    return {'status': 'PASS_ASSET_VALIDATION_ONLY', 'cases': len(cases), 'gold_units': len(units),
            'documents': len(documents), 'families': dict(Counter(c['family'] for c in cases)),
            'labels': dict(Counter(c['expected_label'] for c in cases)), 'contrast_pairs': len(pairs),
            'old_gold_overlap': 0, 'old_query_reuse': 0, 'professional_reviewed': 0,
            'production_baseline_at_freeze': manifest['baseline_status'], 'clinical_correctness_verified': False,
            'production_fingerprints_checked': check_production}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, default=DEFAULT)
    parser.add_argument('--check-production', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = validate(args.folder, args.check_production)
    if args.output:
        require(not args.output.exists(), '结果已存在，不覆盖旧证据')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
