"""独立复核原始生产输出。缺能力不补预测、不计正确，不输出混合总准确率。"""
import json
from collections import Counter
from pathlib import Path

from score import score
from verify import DEFAULT, digest, load, require, validate

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / '.ai/tasks/2026-10-09-evidence-support/baseline-v2'


def summarize(dataset, inputs, raw):
    cases = {c['id']: c for c in dataset['cases']}
    items = {c['id']: c for c in inputs['cases']}
    rows = raw['rows']
    require(len(rows) == len(cases) == len(items), '记录缺题')
    require(len({r['id'] for r in rows}) == len(rows) and {r['id'] for r in rows} == set(cases), 'ID重复或题集不同')
    projection, scored_cases = [], []
    counter = Counter()
    for row in rows:
        require(row['family'] == cases[row['id']]['family'], '题型变更')
        require(row['elapsed_ms'] >= 0, '耗时无效')
        require(row['semantic_judgment_verified'] is False, '不得把逐字核对冒充NLI')
        family = row['family']
        counter[row['status']] += 1
        if family == 'applicability':
            require(row['status'] == 'capability_absent' and row['label'] is None and row['method'] is None
                    and row['raw_output'] is None, '缺能力不能用unknown或其他预测补齐')
            continue
        require(row['status'] == 'executed', '生产执行异常，不能算通过')
        item = items[row['id']]
        if family in ('query_specificity', 'version_scope'):
            retained = bool(row['raw_output'])
            require(row['method'] == 'rank_knowledge_citations' and row['policy_retained'] == retained, '来源门禁原始结果不一致')
            expected_label = ('answers' if retained else 'does_not_answer') if family == 'query_specificity' else (
                'version_match' if retained else 'version_mismatch')
            require(row['label'] == expected_label, '来源门禁投影标签错误')
            for citation in row['raw_output']:
                require(citation['excerpt'] == item['candidate_source']['quote'], '运行摘录被改写')
                require(citation['document_id'] == item['candidate_source']['document_id'], '来源文档不同')
                require(citation['title'] == item['candidate_source']['title'], '来源标题不同')
        else:
            evidence = row['raw_output']
            require(len(evidence) == 1, '陈述记录数错误')
            require(evidence[0]['claim'] == item['statement'], '运行陈述与输入不同')
            require(evidence[0]['status'] in {'excerpt_matched', 'needs_review'}, '生产核对状态未知')
            expected_label = 'supported' if evidence[0]['status'] == 'excerpt_matched' else 'insufficient'
            require(row['label'] == expected_label, '陈述投影标签错误')
        projection.append({'id': row['id'], 'label': row['label']})
        scored_cases.append(cases[row['id']])
    missing_count = sum(c['family'] == 'applicability' for c in cases.values())
    require(counter == Counter({'executed': len(cases) - missing_count, 'capability_absent': missing_count}), '覆盖或错误计数异常')
    # 只评分有实际入口的诊断记录，不将其总分当完整题库成绩。
    projected = score({**dataset, 'cases': scored_cases}, {'predictions': projection})
    by_id = {r['id']: r for r in rows}
    query = [c for c in cases.values() if c['family'] == 'query_specificity']
    positives = [c for c in query if c['expected_label'] == 'answers']
    negatives = [c for c in query if c['expected_label'] == 'does_not_answer']
    partial = [c for c in query if c['expected_label'] == 'partial_answer']
    support = [r for r in rows if r['family'] == 'statement_support']
    versions = [r for r in rows if r['family'] == 'version_scope']
    methods = Counter(c['relevance_method'] for r in rows if r['family'] == 'query_specificity' for c in r['raw_output'])
    return {
        'status': 'BASELINE_RECORDED_WITH_CAPABILITY_GAPS' if missing_count else 'BASELINE_RECORDED_GATE_PROXY_ONLY', 'recorded_cases': len(cases),
        'production_function_executions': len(cases) - missing_count, 'capability_absent': missing_count, 'execution_errors': 0,
        'all_52_semantic_accuracy': None, 'full_52_scoring_permitted': False,
        'all_cases_semantic_accuracy': None, 'full_set_scoring_permitted': False,
        'dataset_version': dataset['version'],
        'query_gate': {'total': len(query), 'true_evidence_retained': sum(by_id[c['id']]['policy_retained'] for c in positives),
                       'true_evidence_total': len(positives),
                       'wrong_topic_retained': sum(by_id[c['id']]['policy_retained'] for c in negatives),
                       'wrong_topic_total': len(negatives), 'retained_methods': dict(methods),
                       'partial_answer_retained': sum(by_id[c['id']]['policy_retained'] for c in partial),
                       'partial_answer_total': len(partial),
                       'partial_answer_meaning': '部分回答保留不自动算无关；保留也不等于完整回答',
                       'meaning': '候选保留诊断，不代表系统已判断语义回答正确'},
        'statement_gate': {'total': len(support), 'raw_statuses': dict(Counter(r['raw_output'][0]['status'] for r in support)),
                           'true_paraphrase_confirmed': sum(r['label'] == 'supported' and cases[r['id']]['expected_label'] == 'supported' for r in support),
                           'true_paraphrase_total': sum(c['family'] == 'statement_support' and c['expected_label'] == 'supported' for c in cases.values()),
                           'false_statement_confirmed': sum(r['label'] == 'supported' and cases[r['id']]['expected_label'] == 'contradicted' for r in support),
                           'false_statement_total': sum(c['family'] == 'statement_support' and c['expected_label'] == 'contradicted' for c in cases.values()), 'meaning': '逐字核对与待审核行为；不能判定意译正确或矛盾'},
        'applicability_gate': {'total': missing_count, 'executed': 0, 'capability_absent': missing_count, 'accuracy': None},
        'version_gate': {'total': len(versions), 'old_edition_filtered': sum(r['label'] == 'version_mismatch' for r in versions),
                         'meaning': '仅显式年份来源过滤诊断；该题库无版本题时不评价版次能力'},
        'projection_families': projected['families'], 'projection_errors': projected['errors'],
        'contrast_pairs_scored': projected['contrast_pairs_total'],
        'contrast_pairs_both_correct': projected['contrast_pairs_both_correct'],
        'contrast_pairs_capability_absent': len({c['pair_id'] for c in cases.values() if c['family'] == 'applicability' and c['pair_id']}),
        'professional_reviewed': dataset['professional_reviewed'], 'not_blind': dataset['not_blind'],
        'clinical_correctness_verified': False,
    }


def verify(folder=BASELINE, check_production=False, assets_dir=DEFAULT):
    # 默认验证历史存档；后续生产优化不应使真实旧记录无法复核。
    validate(assets_dir, check_production=check_production)
    manifest, dataset, inputs = [load(assets_dir / name) for name in ['manifest.json', 'dataset.json', 'inputs.json']]
    full = folder / 'full'
    raw, executed_inputs, execution = [load(full / name) for name in ['observations.json', 'execution-input.json', 'execution.json']]
    require(executed_inputs == inputs, '完整运行输入不是冻结输入')
    require(raw['input_sha256'] == digest(assets_dir / 'inputs.json') and raw['execution_input_sha256'] == digest(full / 'execution-input.json'), '输入指纹不符')
    require(raw['version'] == dataset['version'], '版本不符')
    require(raw['all_52_semantic_accuracy'] is None, '旧基线不得含伪造完整语义总分')
    require(raw['read_only'] and raw['rolled_back'] and raw['settings_unchanged'], '只读及配置不变门禁失败')
    require(raw['settings_before'] == raw['settings_after'], '额度或保护改变')
    require(raw['observed_http_attempts'] == raw['extra_model_calls'] == 0, '有意外网络调用')
    require(raw['database_source_spans_verified'] == manifest['gold_units'], '当前数据库原文未全部核对')
    require(raw['vector_retrieval_executed'] is False and raw['external_search_executed'] is False, '实验范围不一致')
    require(execution['docker_exit_code'] == 0 and execution['read_gold_in_executor'] is False, '执行错误或gold泄漏')
    for name, sha in manifest['production_sha256'].items():
        require(raw['source_sha256'][name.removeprefix('backend/')] == sha, '容器源码漂移')
    require(execution['runtime_sha256'] == digest(full / 'runtime.py'), '执行器快照不同')
    require(execution['runner_sha256'] == digest(full / 'runner.py'), 'runner快照不同')
    smoke = load(folder / 'smoke/observations.json')
    require(load(folder / 'smoke/execution.json')['runtime_sha256'] == execution['runtime_sha256'], '小样本与完整运行协议不同')
    actual = {r['id']: r for r in raw['rows']}
    for row in smoke['rows']:
        require(row['id'] in actual and {k: v for k, v in row.items() if k != 'elapsed_ms'} ==
                {k: v for k, v in actual[row['id']].items() if k != 'elapsed_ms'}, '小样本与完整运行观测发生漂移')
    result = summarize(dataset, inputs, raw)
    result.update(input_sha256=digest(assets_dir / 'inputs.json'), dataset_sha256=digest(assets_dir / 'dataset.json'),
                  observations_sha256=digest(full / 'observations.json'),
                  scorer_sha256=digest(Path(__file__).with_name('score.py')),
                  verifier_sha256=digest(Path(__file__)))
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--folder', type=Path, default=BASELINE)
    parser.add_argument('--check-production', action='store_true')
    parser.add_argument('--assets-dir', type=Path, default=DEFAULT)
    args = parser.parse_args()
    result = verify(args.folder, check_production=args.check_production, assets_dir=args.assets_dir)
    if args.output:
        require(not args.output.exists(), '不覆盖旧基线记录')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ['projection_families', 'projection_errors']}, ensure_ascii=False))
