"""新题集固定评分；原始观测是外部输入，金标只在离线评分时读取。"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

from build_resume_eval import load, require, sha, validate

LABELS = ('answers', 'partial_answer', 'does_not_answer')
GRADES = {'answers': 2, 'partial_answer': 1, 'does_not_answer': 0}
KS = (5, 10)


def intervals_cover(intervals, start, end, text):
    """不要求PDF空白命中，但每个非空白原文字符都必须在来源坐标中。"""
    cursor = start
    for left, right in sorted(intervals):
        if right <= cursor:
            continue
        if left > cursor and text[cursor:min(left, end)].strip():
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return not text[cursor:end].strip()


def validate_source(source, docs):
    require(set(source) == {'document_id', 'start', 'end', 'quote'}, '检索来源字段非法')
    require(source['document_id'] in docs, '检索文档不存在')
    a, b = source['start'], source['end']
    require(type(a) is int and type(b) is int, '原文坐标必须是整数')
    text = docs[source['document_id']]['content']
    require(0 <= a < b <= len(text) and text[a:b] == source['quote'], '引文与原文坐标不一致')


def retrieval_metrics(gold, sources, docs, full_source, error):
    results = {}
    for k in KS:
        selected = sources[:k]
        if not gold['answerable']:
            results[str(k)] = {'hit': None, 'annotated_evidence_recall': None, 'complete_evidence': None,
                               'necessary_claim_coverage': None, 'mrr': None, 'unsupported_returned': bool(selected)}
            continue
        ranges = {}
        for s in selected:
            ranges.setdefault(s['document_id'], []).append((s['start'], s['end']))
        required = gold['requirements']
        covered = [intervals_cover(ranges.get(r['document_id'], []), r['start'], r['end'], docs[r['document_id']]['content']) for r in required]
        hit = any(s['document_id'] == r['document_id'] and max(s['start'], r['start']) < min(s['end'], r['end']) for s in selected for r in required)
        first = next((i + 1 for i, s in enumerate(selected) if any(s['document_id'] == r['document_id'] and max(s['start'], r['start']) < min(s['end'], r['end']) for r in required)), None)
        results[str(k)] = {'hit': bool(hit) and not error,
                          'annotated_evidence_recall': sum(covered) / len(covered) if not error else 0,
                          'complete_evidence': intervals_cover(ranges.get(full_source['document_id'], []), full_source['start'], full_source['end'], docs[full_source['document_id']]['content']) and not error,
                          'necessary_claim_coverage': all(covered) and not error,
                          'mrr': 1 / first if first and not error else 0,
                          'unsupported_returned': None}
    rank = next((i + 1 for i, s in enumerate(sources) if any(s['document_id'] == r['document_id'] and max(s['start'], r['start']) < min(s['end'], r['end']) for r in gold['requirements'])), None)
    return results, (1 / rank if rank and not error else 0) if gold['answerable'] else None


def ndcg(order, labels):
    def dcg(ids):
        return sum((2 ** GRADES[labels[sid]] - 1) / math.log2(i + 2) for i, sid in enumerate(ids))
    ideal = dcg(sorted(labels, key=lambda sid: GRADES[labels[sid]], reverse=True))
    return dcg(order) / ideal if ideal else None


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f'{name}必须为非负有限数字')


def score(assets, observations, split, *, retrieval_executed=True, selected_ids=None):
    require(type(retrieval_executed) is bool, '执行范围必须明确')
    validate(assets)
    require(split in {'development', 'holdout'}, '集合非法')
    inputs = load(assets / f'inputs-{split}.json')
    gold_data = load(assets / 'gold.json')
    docs = {d['id']: d for d in load(assets / 'corpus.json')['documents']}
    questions = {q['id']: q for q in inputs['questions']}
    golds = {q['id']: q for q in gold_data['questions'] if q['split'] == split}
    require(set(questions) == set(golds) and bool(questions), '输入与金标集合不同或空')
    if selected_ids is not None:
        require(isinstance(selected_ids, (list, tuple, set)) and bool(selected_ids)
                and len(selected_ids) == len(set(selected_ids)) and set(selected_ids) <= set(questions), '烟测选择非法')
        questions = {key: value for key, value in questions.items() if key in selected_ids}
        golds = {key: value for key, value in golds.items() if key in selected_ids}
    require(set(observations) == {'protocol', 'split', 'input_sha256', 'rows'}, '观测顶层字段非法/可能泄漏gold')
    require(observations['protocol'] == 'resume-eval-observations-v1' and observations['split'] == split, '观测协议或集合非法')
    require(observations['input_sha256'] == sha((assets / f'inputs-{split}.json').read_bytes()), '执行输入指纹不同')
    rows = observations['rows']
    ids = [r.get('id') for r in rows]
    require(len(ids) == len(set(ids)) == len(questions) and set(ids) == set(questions), '缺失、重复或额外结果，拒绝改变分母')
    confusion, class_totals = Counter(), Counter()
    false_delete = Counter()
    false_keep, unknowns, errors = 0, 0, 0
    candidate_rows, retrieval_rows, ndcgs, elapsed, usage = [], [], [], [], []
    for row in rows:
        require(set(row) == {'id', 'status', 'retrieved_sources', 'candidates', 'ranked_ids', 'elapsed_ms', 'usage', 'error_type'}, '逐题观测字段非法/可能泄漏gold')
        require(row['status'] in {'success', 'error'}, '观测状态非法')
        error = row['status'] == 'error'
        require((error and isinstance(row['error_type'], str) and bool(row['error_type'])) or (not error and row['error_type'] is None), '错误必须显式记录')
        errors += error
        q, g = questions[row['id']], golds[row['id']]
        labels = {s['id']: s['label'] for s in g['candidates']}
        sources = row['retrieved_sources']
        require(isinstance(sources, list), '检索来源必须是数组')
        require(retrieval_executed or not sources, '候选判断评测不得伪装检索来源')
        for source in sources:
            validate_source(source, docs)
        require(len({(s['document_id'], s['start'], s['end']) for s in sources}) == len(sources), '检索来源重复')
        predicted = row['candidates']
        require(isinstance(predicted, list) and len(predicted) == len(labels) and {p.get('id') for p in predicted} == set(labels), '候选预测缺失、重复或额外')
        retained = set()
        for p in predicted:
            require(set(p) == {'id', 'label', 'retain', 'score'}, '候选输出字段非法')
            require(p['label'] in (*LABELS, 'unknown') and type(p['retain']) is bool, '标签或保留状态非法')
            if error:
                require(p['label'] == 'unknown' and p['retain'] and p['score'] is None, '错误不能伪装有效分类')
            else:
                number(p['score'], '候选分数')
                require(p['score'] <= 1, '候选分数越界')
            if p['label'] == 'unknown':
                require(p['retain'], '未知候选不得静默删除')
                unknowns += 1
            expected = labels[p['id']]
            confusion[expected + ' -> ' + p['label']] += 1
            class_totals[expected] += 1
            if p['retain']:
                retained.add(p['id'])
            false_delete[expected] += int(not p['retain'] and expected in {'answers', 'partial_answer'})
            false_keep += int(p['retain'] and expected == 'does_not_answer')
            candidate_rows.append({'question_id': row['id'], 'source_id': p['id'], 'expected': expected, 'predicted': p['label'], 'retain': p['retain']})
        order = row['ranked_ids']
        require(isinstance(order, list) and len(order) == len(set(order)) and set(order) == retained, '排序必须与保留候选完整一致')
        # 错误的排名得0分，不能靠回退顺序恰巧有用取得成功成绩。
        value = ndcg(order, labels)
        if value is not None:
            ndcgs.append(0 if error else value)
        full = next((s for s in q['candidates'] if s['id'] == g['full_source_id']), None)
        metrics, mrr = retrieval_metrics(g, sources, docs, full, error)
        retrieval_rows.append({'id': row['id'], 'status': row['status'], 'answerable': g['answerable'], 'at_k': metrics, 'mrr_all_returned': mrr})
        number(row['elapsed_ms'], '耗时')
        elapsed.append(row['elapsed_ms'])
        require(set(row['usage']) == {'input_tokens', 'output_tokens'}, 'usage字段非法')
        for name, value in row['usage'].items():
            require(value is None or (type(value) is int and value >= 0), 'usage必须是实测非负整数或null')
        usage.append(row['usage'])
    per_class = {}
    for label in LABELS:
        tp = confusion[label + ' -> ' + label]
        fp = sum(v for key, v in confusion.items() if key.endswith(' -> ' + label) and key != label + ' -> ' + label)
        fn = class_totals[label] - tp
        per_class[label] = {'support': class_totals[label], 'precision': tp / (tp + fp) if tp + fp else 0,
                            'recall': tp / (tp + fn) if tp + fn else 0,
                            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}
    positives = [r for r in retrieval_rows if r['answerable']]
    negatives = [r for r in retrieval_rows if not r['answerable']]
    retrieval = {}
    for k in KS:
        key = str(k)
        avg = lambda name: sum(r['at_k'][key][name] for r in positives) / len(positives) if positives else None
        retrieval[key] = {'hit_at_k': avg('hit'), 'annotated_evidence_recall_at_k': avg('annotated_evidence_recall'),
                          'complete_evidence_rate': avg('complete_evidence'), 'necessary_claim_coverage_rate': avg('necessary_claim_coverage'),
                          'mrr_at_k': avg('mrr'),
                          # 无答案执行失败不是正确拒答；有失败则实际误召回率未知，不报更好成绩。
                          'no_answer_false_retrieval_rate': None if not negatives or any(r['status'] == 'error' for r in negatives) else sum(r['at_k'][key]['unsupported_returned'] for r in negatives) / len(negatives),
                          'no_answer_gate_failure_rate': sum(r['status'] == 'error' or r['at_k'][key]['unsupported_returned'] for r in negatives) / len(negatives) if negatives else None,
                          'no_answer_execution_errors': sum(r['status'] == 'error' for r in negatives)}
    token_totals = {name: sum(u[name] for u in usage) if all(u[name] is not None for u in usage) else None for name in ('input_tokens', 'output_tokens')}
    n = len(candidate_rows)
    return {'status': 'OBSERVATIONS_SCORED' if not errors and not unknowns else 'OBSERVATIONS_WITH_ERRORS',
            'split': split, 'groups': len(rows), 'answerable': len(positives), 'no_answer': len(negatives), 'candidate_rows': n,
            'accuracy': sum(r['expected'] == r['predicted'] for r in candidate_rows) / n,
            'per_class': per_class, 'macro_f1': sum(v['f1'] for v in per_class.values()) / len(LABELS),
            'confusion': dict(confusion), 'false_delete': dict(false_delete), 'false_keep': false_keep,
            'unknowns': unknowns, 'execution_errors': errors, 'mean_candidate_ndcg': sum(ndcgs) / len(ndcgs) if ndcgs else None,
            'candidate_ndcg_k': 'each_question_candidate_count_2_to_4', 'retrieval': retrieval if retrieval_executed else None,
            'mrr_all_returned': sum(r['mrr_all_returned'] for r in positives) / len(positives) if retrieval_executed and positives else None,
            'metric_scope': 'retrieval_and_candidates' if retrieval_executed else 'given_candidates_only',
            'evaluation_scope': 'full_split' if selected_ids is None else 'explicit_smoke_subset',
            'usage': token_totals, 'usage_complete_groups': sum(all(v is not None for v in u.values()) for u in usage),
            'elapsed_ms_total': sum(elapsed), 'elapsed_ms_mean': sum(elapsed) / len(elapsed),
            'candidate_results': candidate_rows, 'retrieval_results': retrieval_rows if retrieval_executed else None,
            'clinical_accuracy': None, 'recall_scope': 'annotated necessary original spans; not exhaustive corpus relevance',
            'qualifier_coverage': 'necessary_claim_coverage requires complete annotated claims including conditions, not keyword matching'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--split', choices=['development', 'holdout'], required=True)
    parser.add_argument('--candidate-only', action='store_true')
    parser.add_argument('--selected-ids', nargs='+')
    args = parser.parse_args()
    result = score(args.assets, load(args.observations), args.split, retrieval_executed=not args.candidate_only, selected_ids=args.selected_ids)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    require(result['status'] == 'OBSERVATIONS_SCORED', '存在错误或未知，停止扩量；指标仅作诊断')
