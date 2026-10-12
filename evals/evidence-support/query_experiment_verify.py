"""离线重算真实实验与输入/校准链，不执行存档脚本，不调用模型。"""
import argparse
import json
from pathlib import Path
from query_experiment import TASK, groups_from_inputs, quality
from verify import validate, load, digest, require
from app.services.query_requirements import parse_assessment, rank_assessed


def verify_run(folder, assets, partial=False, stack=None):
    stack = set() if stack is None else stack
    folder = folder.resolve()
    folder.relative_to(TASK.resolve())
    require(folder not in stack and len(stack) < 10, '父级记录循环或过深')
    stack = stack | {folder}
    validate(assets)
    execution, data = load(folder / 'execution.json'), load(folder / 'observations.json')
    require(execution['docker_exit_code'] == 0 and execution['read_gold_in_executor'] is False, '非真实无gold执行协议')
    require(execution['assets_sha256'] == digest(assets / 'inputs.json'), '题集指纹不同')
    for name, key in [('assessor.py', 'assessor_sha256'), ('runtime.py', 'runtime_sha256'), ('runner.py', 'runner_sha256')]:
        require(digest(folder / name) == execution[key], '执行源码快照不符：' + name)
    all_groups = groups_from_inputs(load(assets / 'inputs.json'))
    lookup = {g['id']: g for g in all_groups}
    calibrated = execution.get('kind') in {'literal_quote_protocol_calibration', 'literal_quote_length_calibration'}
    if calibrated:
        original = Path(execution['original'])
        require(digest(original / 'observations.json') == execution['original_observations_sha256'], '校准原始输出变化')
        verify_run(original, assets, partial=True, stack=stack)
        raw = load(original / 'observations.json')
        old = (original / 'assessor.py').read_text(encoding='utf-8')
        adjusted = old.replace("len(''.join(quote.split())) >= 4", "len(''.join(quote.split())) >= 1")
        line = "            covered, quote, reason = (check[k] for k in ('covered', 'quote', 'reason'))\n"
        addition = "            if covered is not True and quote == 'null':\n                check['quote'] = quote = None\n"
        if execution['kind'] == 'literal_quote_protocol_calibration' and addition not in adjusted:
            adjusted = adjusted.replace(line, line + addition)
        require(adjusted == (folder / 'assessor.py').read_text(encoding='utf-8'), '校准变更超出短词与空值协议')
        for group in raw['groups']:
            sources = [{'id': c['id'], 'excerpt': c['candidate_source']['quote']} for c in lookup[group['id']]['cases']]
            group['assessment'].update(parse_assessment(group['assessment']['raw_output'], sources), status='assessed', error_type=None)
            group['after_order'] = rank_assessed(group['assessment'])
        require(raw == data and execution['extra_http_requests'] == 0, '校准改写了原始模型内容或运行状态')
    else:
        payload = load(folder / 'execution-input.json')
        require(digest(folder / 'execution-input.json') == execution['input_sha256'], '执行输入指纹不同')
        require(payload['version'] == data['version'] == load(assets / 'inputs.json')['version'], '题集版本混用')
        require(payload['source_sha256'] == data['source_sha256'], '运行源码记录不同')
        require(data['source_sha256']['app/services/query_requirements.py'] == execution['assessor_sha256'], '实际判别源码与快照不同')
        for key, expected in load(assets / 'manifest.json')['production_sha256'].items():
            require(data['source_sha256'][key.removeprefix('backend/')] == expected, '实验前生产代码漂移')
        for group in payload['groups']:
            require(group == lookup.get(group['id']), '实际输入不是冻结候选或包含答案提示')
        require(len({g['id'] for g in payload['groups']}) == len(payload['groups']), '输入分组重复')
        inherited = []
        if execution.get('parent_smoke'):
            parent = Path(execution['parent_smoke'])
            require(digest(parent / 'observations.json') == execution['parent_observations_sha256'], '继承原始输出不同')
            verify_run(parent, assets, partial=True, stack=stack)
            parent_data = load(parent / 'observations.json')
            inherited = parent_data['groups']
            require({g['id'] for g in inherited}.isdisjoint({g['id'] for g in payload['groups']}), '继承与新执行重复')
            actual = {g['id']: g for g in data['groups']}
            require(all(actual.get(g['id']) == g for g in inherited), '继承结果改写')
            require(data['requests'][:len(parent_data['requests'])] == parent_data['requests'], '继承HTTP记录改写')
        require({g['id'] for g in data['groups']} <= {g['id'] for g in payload['groups']} | {g['id'] for g in inherited}, '输出额外分组')
    require(data['read_only'] and data['rolled_back'] and data['read_gold'] is False and data['settings_unchanged']
            and data['settings_before'] == data['settings_after'], '只读/保护/输入隔离门禁破坏')
    require(data['vector_retrieval_executed'] is False and data['external_search_executed'] is False
            and data['clinical_correctness_verified'] is False, '夸大评测范围')
    for group in data['groups']:
        expected = lookup.get(group['id'])
        require(expected and group['query'] == expected['query'] and group['case_ids'] == [c['id'] for c in expected['cases']], '观测输入ID/query不同')
        for row, cid in zip(group['before_sources'], group['before_order']):
            item = next(c for c in expected['cases'] if c['id'] == cid)
            source = item['candidate_source']
            require(row['excerpt'] == source['quote'] and row['title'] == source['title']
                    and row['document_id'] == source['document_id'] and row['url'] == source['source_url'], '原始来源内容或出处漂移')
    if data['protocol'] == 'query_requirements_paired_v2':
        require(len(data['requests']) == len(data['groups']) and all(g['http_attempts'] == 1 for g in data['groups']), 'HTTP计数不等于实际逐组调用')
        require(all(r['status_code'] == 200 and r['native_usage'] for r in data['requests']), 'HTTP失败或原生usage缺失')
    else:
        require(data['protocol'] == 'query_requirements_paired_v1' and not data['requests'], '未知执行协议')
    ids = {cid for g in data['groups'] for cid in g['case_ids']}
    selected = ids if partial or execution['mode'] == 'smoke' or calibrated else None
    metrics = quality(load(assets / 'dataset.json'), data, selected)
    if (folder / 'score.json').exists(): require(metrics == load(folder / 'score.json'), '存档评分与复算不同')
    return metrics


def verify_all(root=TASK / 'query-assessment-v3'):
    dev = verify_run(root / 'dev-full', TASK / 'query-development-v2')
    regression = verify_run(root / 'v4-full', TASK / 'frozen-v4')
    first = verify_run(TASK / 'query-assessment-v1/dev-full', TASK / 'query-development-v2')
    require(dev['cases'] == 24 and regression['cases'] == 16 and first['cases'] == 24, '缺少正式完整运行')
    require(dev['after_retained']['answers'] == dev['after_retained']['partial_answer'] == 8
            and dev['after_retained']['does_not_answer'] < 8, '开发保留/过滤门禁失败')
    require(regression['after_retained']['answers'] == 8 and regression['after_retained']['does_not_answer'] <= 6, '回归保留/过滤门禁失败')
    differences = [r['id'] for r in dev['rows'] if r['predicted'] != next(x for x in first['rows'] if x['id'] == r['id'])['predicted']]
    runs = [load(path / 'observations.json') for path in
            (root / 'dev-full', root / 'v4-full', TASK / 'query-assessment-v1/dev-full')]
    successful_calls = sum(len(run['groups']) for run in runs)
    observed_calls = sum(len(run['requests']) for run in runs)
    return {'status': 'VERIFIED_PAIRED_EXPERIMENT_ONLY', 'development': dev, 'regression': regression,
            'repeat_prediction_differences': differences, 'successful_model_calls': successful_calls,
            'sdk_http_calls_observed': observed_calls, 'first_run_http_calls': None, 'professional_reviewed': 0,
            'scope': '给定候选内容判断及排序；非召回、非完整问诊、非临床验证'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify_all()
    if args.output:
        require(not args.output.exists(), '不得覆盖验证记录')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: ({n: v for n, v in value.items() if n != 'rows'} if isinstance(value, dict) else value)
                      for k, value in result.items()}, ensure_ascii=False))
