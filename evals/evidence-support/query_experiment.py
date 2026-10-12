"""冻结协议的配对实验与严格复算；真实模型观测不能由gold生成。"""
import argparse
import base64
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from collections import Counter
from verify import ROOT, validate, digest, load, require

TASK = ROOT / '.ai/tasks/2026-10-09-evidence-support'
ASSESSOR = ROOT / 'backend/app/services/query_requirements.py'
RUNTIME = Path(__file__).with_name('query_experiment_runtime.py')
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.query_requirements import parse_assessment, rank_assessed


def groups_from_inputs(inputs):
    grouped = {}
    for item in inputs['cases']:
        if item['family'] != 'query_specificity': continue
        grouped.setdefault(item['query'], []).append(item)
    groups = [{'id': hashlib.sha256(q.encode()).hexdigest()[:16], 'query': q,
               'cases': sorted(items, key=lambda c: c['id'])} for q, items in grouped.items()]
    return sorted(groups, key=lambda g: g['id'])


def quality(dataset, observations, selected_ids=None):
    expected = {c['id']: c for c in dataset['cases'] if c['family'] == 'query_specificity'
                and (selected_ids is None or c['id'] in selected_ids)}
    require(bool(expected), '不能评分空集')
    seen, confusion, class_counts = set(), Counter(), {}
    before_keep, after_keep, before_ndcg, after_ndcg, rows = Counter(), Counter(), [], [], []
    errors = 0
    for group in observations['groups']:
        result = group['assessment']
        require(set(group['case_ids']) <= set(expected), '额外执行ID')
        require(not (seen & set(group['case_ids'])), '执行ID重复')
        seen.update(group['case_ids'])
        cases = {cid: expected[cid] for cid in group['case_ids']}
        require(len({c['query'] for c in cases.values()}) == 1 and group['query'] == next(iter(cases.values()))['query'], '分组query不同')
        require({r['id'] for r in result['candidates']} == set(cases) and len(result['candidates']) == len(cases), '预测缺失或重复')
        if result['status'] == 'assessed':
            sources = [{'id': cid, 'excerpt': next(u for u in dataset['gold_units'] if u['id'] == cases[cid]['candidate_evidence_id'])['quote']}
                       for cid in group['case_ids']]
            parsed = parse_assessment(result['raw_output'], sources)
            require(parsed['requirements'] == result['requirements'] and parsed['candidates'] == result['candidates'], '模型原输出与评分记录不同')
        else:
            require(result['status'] == 'assessment_error' and all(r['label'] == 'unknown' and r['retain'] for r in result['candidates']), '失败伪装为成功')
            errors += 1
        require(group['after_order'] == rank_assessed(result), '实验排序与覆盖口径不符')
        for order in (group['before_order'], group['after_order']):
            require(len(set(order)) == len(order) and set(order) <= set(cases), '排序重复或多余来源')
        for row in result['candidates']:
            cid, predicted = row['id'], row['label']
            gold = cases[cid]['expected_label']
            require(predicted in {'answers', 'partial_answer', 'does_not_answer', 'unknown'}, '预测标签非法')
            confusion[gold + ' -> ' + predicted] += 1
            class_counts[gold] = class_counts.get(gold, 0) + 1
            before_keep[gold] += int(cid in group['before_order'])
            after_keep[gold] += int(row['retain'])
            rows.append({'id': cid, 'display_id': cases[cid].get('display_id'), 'expected': gold, 'predicted': predicted,
                         'correct': gold == predicted, 'before_retained': cid in group['before_order'],
                         'after_retained': row['retain'], 'missing_requirements': row['missing_requirements']})
        gains = {'answers': 2, 'partial_answer': 1, 'does_not_answer': 0}
        k = len(cases)
        ideal = sum((2 ** v - 1) / math.log2(i + 2) for i, v in enumerate(sorted([gains[c['expected_label']] for c in cases.values()], reverse=True)))
        for order, results in ((group['before_order'], before_ndcg), (group['after_order'], after_ndcg)):
            dcg = sum((2 ** gains[cases[cid]['expected_label']] - 1) / math.log2(i + 2) for i, cid in enumerate(order[:k]))
            results.append(dcg / ideal if ideal else None)
    require(seen == set(expected), '缺失结果不得从分母排除')
    f1s = []
    for label in class_counts:
        tp = confusion[label + ' -> ' + label]
        fp = sum(v for key, v in confusion.items() if key.endswith(' -> ' + label) and key != label + ' -> ' + label)
        fn = class_counts[label] - tp
        f1s.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return {'cases': len(rows), 'correct': sum(r['correct'] for r in rows), 'accuracy': sum(r['correct'] for r in rows) / len(rows),
            'macro_f1': sum(f1s) / len(f1s), 'confusion': dict(confusion), 'class_totals': class_counts,
            'before_retained': dict(before_keep), 'after_retained': dict(after_keep), 'assessment_errors': errors,
            'unknown_count': sum(r['predicted'] == 'unknown' for r in rows),
            'ranking_k': len(next(iter(observations['groups']))['case_ids']),
            'ndcg_before': sum(v for v in before_ndcg if v is not None) / len(before_ndcg),
            'ndcg_after': sum(v for v in after_ndcg if v is not None) / len(after_ndcg), 'rows': rows,
            'recall_at_k': None, 'clinical_correctness_verified': False}


def execute(assets, output, mode, parent=None):
    validate(assets, check_production=True)
    output.resolve().relative_to(TASK.resolve())
    inputs = load(assets / 'inputs.json')
    all_groups = groups_from_inputs(inputs)
    require(len(all_groups) == 8, '协议要求8问题')
    selected = all_groups[:2] if mode == 'smoke' else all_groups
    inherited = []
    if mode == 'full':
        require(parent is not None, '全量必须有烟测目录')
        smoke = load(parent / 'observations.json')
        gate = load(parent / 'score.json')
        smoke_count = 6 if inputs['version'].startswith('query-development') else 4
        require(gate['cases'] >= smoke_count and len(smoke['groups']) >= 2
                and [g['id'] for g in smoke['groups']] == [g['id'] for g in all_groups[:len(smoke['groups'])]], '烟测/续跑前缀数量错误')
        require(gate['correct'] == gate['cases'] and gate['assessment_errors'] == gate['unknown_count'] == 0, '烟测质量未放行')
        protocol = load(parent / 'execution.json')
        calibrated = protocol.get('kind') == 'literal_quote_protocol_calibration'
        require(protocol['assets_sha256'] == digest(assets / 'inputs.json') and protocol['assessor_sha256'] == digest(ASSESSOR)
                and protocol['runtime_sha256'] == digest(RUNTIME) and protocol['runner_sha256'] == digest(Path(__file__)), '烟测协议漂移')
        inherited = smoke['groups']
        selected = [g for g in selected if g['id'] not in {r['id'] for r in inherited}]
    manifest = load(assets / 'manifest.json')
    hashes = {name.removeprefix('backend/'): sha for name, sha in manifest['production_sha256'].items()}
    hashes['app/services/llm.py'] = digest(ROOT / 'backend/app/services/llm.py')
    hashes['app/services/interview_demo.py'] = digest(ROOT / 'backend/app/services/interview_demo.py')
    hashes['app/services/query_requirements.py'] = digest(ASSESSOR)
    payload = {'version': inputs['version'], 'groups': selected, 'source_sha256': hashes}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'assessor.py').write_bytes(ASSESSOR.read_bytes())
    (output / 'runtime.py').write_bytes(RUNTIME.read_bytes())
    (output / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (output / 'execution-input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    code = ('import asyncio,base64,json,types\n'
            "m=types.ModuleType('query_runtime');m.__file__='/tmp/query_runtime.py'\n"
            f"exec(base64.b64decode({base64.b64encode(RUNTIME.read_bytes()).decode()!r}),m.__dict__)\n"
            f"p=json.loads(base64.b64decode({base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()!r}))\n"
            'print(json.dumps(asyncio.run(m.evaluate(p)),ensure_ascii=False,allow_nan=False))\n')
    result = subprocess.run(['docker', 'exec', '-i', '-w', '/app', 'medaxis-backend', 'python', '-'], input=code,
                            capture_output=True, text=True, encoding='utf-8', timeout=600)
    execution = {'docker_exit_code': result.returncode, 'assets_sha256': digest(assets / 'inputs.json'),
                 'assessor_sha256': digest(ASSESSOR), 'runtime_sha256': digest(RUNTIME), 'runner_sha256': digest(Path(__file__)),
                 'input_sha256': digest(output / 'execution-input.json'), 'mode': mode,
                 'parent_smoke': str(parent) if inherited else None, 'parent_observations_sha256': digest(parent / 'observations.json') if inherited else None,
                 'stderr_present': bool(result.stderr.strip()), 'read_gold_in_executor': False}
    (output / 'execution.json').write_text(json.dumps(execution, indent=2), encoding='utf-8')
    require(result.returncode == 0, '容器失败；仅保留安全退出码，不输出可能含连接信息的异常')
    data = json.loads(result.stdout)
    if inherited:
        previous_hashes = dict(smoke['source_sha256'])
        if calibrated:
            require(previous_hashes['app/services/query_requirements.py'] == protocol['original_assessor_sha256'], '校准原源码不一致')
            previous_hashes['app/services/query_requirements.py'] = digest(ASSESSOR)
        require(data['settings_before'] == smoke['settings_before'] and data['source_sha256'] == previous_hashes, '扩量环境漂移')
        data['groups'] = sorted(inherited + data['groups'], key=lambda r: r['id'])
        data['requests'] = smoke['requests'] + data['requests']
        data['inherited_smoke_groups'] = len(inherited)
        data['inherited_smoke_calibrated'] = calibrated
    (output / 'observations.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    require(data['settings_unchanged'], '保护/额度变化')
    ids = {item['id'] for g in all_groups[:2] for item in g['cases']} if mode == 'smoke' else None
    metrics = quality(load(assets / 'dataset.json'), data, ids)
    (output / 'score.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in metrics.items() if k != 'rows'}, ensure_ascii=False))
    require(metrics['assessment_errors'] == metrics['unknown_count'] == 0, '模型协议失败或有未知，停止扩量')
    if mode == 'smoke': require(metrics['correct'] == metrics['cases'], '烟测分类不全对，停止扩量')


def calibrate_smoke(assets, original, output):
    """只重算已返回JSON；短词与空值转码校准，模型提示词及金标不变。"""
    validate(assets, check_production=True)
    output.resolve().relative_to(TASK.resolve())
    old_source = (original / 'assessor.py').read_text(encoding='utf-8')
    adjusted = old_source.replace("len(''.join(quote.split())) >= 4", "len(''.join(quote.split())) >= 1")
    line = "            covered, quote, reason = (check[k] for k in ('covered', 'quote', 'reason'))\n"
    addition = "            if covered is not True and quote == 'null':\n                check['quote'] = quote = None\n"
    if addition not in adjusted: adjusted = adjusted.replace(line, line + addition)
    require(adjusted == ASSESSOR.read_text(encoding='utf-8'), '校准只允许短引用/空值转码，不允许改提示词或其它逻辑')
    old_execution = load(original / 'execution.json')
    require(old_execution['docker_exit_code'] == 0 and old_execution['assets_sha256'] == digest(assets / 'inputs.json')
            and digest(original / 'assessor.py') == old_execution['assessor_sha256'], '原始模型执行证据不符')
    data = load(original / 'observations.json')
    original_groups = groups_from_inputs(load(assets / 'inputs.json'))[:len(data['groups'])]
    require(data['protocol'] == 'query_requirements_paired_v2' and data['settings_unchanged']
            and len(data['requests']) == len(data['groups']) >= 2, '原烟测传输证据缺失')
    lookup = {g['id']: g for g in original_groups}
    for group in data['groups']:
        assessment = group['assessment']
        require(bool(assessment['raw_output']), '不能校准未完成的模型输出')
        sources = [{'id': c['id'], 'excerpt': c['candidate_source']['quote']} for c in lookup[group['id']]['cases']]
        assessment.update(parse_assessment(assessment['raw_output'], sources), status='assessed', error_type=None)
        group['after_order'] = rank_assessed(assessment)
    ids = {item['id'] for g in original_groups for item in g['cases']}
    metrics = quality(load(assets / 'dataset.json'), data, ids)
    require(metrics['correct'] == metrics['cases'] and metrics['cases'] >= 6, '校准前缀仍不合格')
    output.mkdir(parents=True, exist_ok=False)
    execution = dict(old_execution, kind='literal_quote_protocol_calibration',
        original=str(original), original_observations_sha256=digest(original / 'observations.json'),
        original_assessor_sha256=old_execution['assessor_sha256'], assessor_sha256=digest(ASSESSOR),
        runtime_sha256=digest(RUNTIME), runner_sha256=digest(Path(__file__)), extra_http_requests=0,
        note='只重算同一模型原始JSON；原始失败保留，不称新模型执行')
    for name, item in [('observations.json', data), ('score.json', metrics), ('execution.json', execution)]:
        (output / name).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, path in [('assessor.py', ASSESSOR), ('runtime.py', RUNTIME), ('runner.py', Path(__file__))]:
        (output / name).write_bytes(path.read_bytes())
    print(json.dumps({'status': 'CALIBRATED_SAME_RAW_MODEL_OUTPUT', 'correct': metrics['correct'], 'cases': metrics['cases'], 'extra_http_requests': 0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['smoke', 'full', 'repeat', 'calibrate'])
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parent', type=Path)
    args = parser.parse_args()
    if args.mode == 'calibrate': calibrate_smoke(args.assets, args.parent, args.output)
    else: execute(args.assets, args.output, args.mode, args.parent)
