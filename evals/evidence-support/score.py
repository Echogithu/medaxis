"""对实际预测严格评分。缺题、重复ID、无效标签直接失败，不丢题算高分。"""
import json
from pathlib import Path

from verify import DEFAULT, LABELS, load, require, validate


def score(dataset, predictions):
    cases = dataset['cases']
    lookup = {c['id']: c for c in cases}
    require(len(lookup) == len(cases), '题库ID重复')
    rows = predictions['predictions']
    guesses = {}
    for row in rows:
        require(row['id'] in lookup, '预测含额外ID')
        require(row['id'] not in guesses, '预测ID重复')
        require(row['label'] in LABELS[lookup[row['id']]['family']], '预测标签非法')
        guesses[row['id']] = row['label']
    require(set(guesses) == set(lookup), '预测缺题，不允许省略失败题')
    groups, pair_groups, errors = {}, {}, []
    for case in cases:
        expected, actual = case['expected_label'], guesses[case['id']]
        correct = expected == actual
        family = case['family']
        group = groups.setdefault(family, {'total': 0, 'correct': 0, 'false_accepts': 0,
                                           'negative_total': 0, 'confusion': {}})
        group['total'] += 1
        group['correct'] += int(correct)
        positive = {'query_specificity': 'answers', 'statement_support': 'supported',
                    'applicability': 'applicable', 'version_scope': 'version_match'}[family]
        group['negative_total'] += int(expected != positive)
        group['false_accepts'] += int(actual == positive and expected != positive)
        confusion_key = expected + ' -> ' + actual
        group['confusion'][confusion_key] = group['confusion'].get(confusion_key, 0) + 1
        if not correct:
            errors.append({'id': case['id'], 'display_id': case.get('display_id'), 'expected': expected, 'actual': actual, 'family': family})
        if case['pair_id']:
            pair_groups.setdefault(case['pair_id'], []).append(correct)
    for group in groups.values():
        group['accuracy'] = group['correct'] / group['total']
        group['false_accept_rate'] = group['false_accepts'] / group['negative_total'] if group['negative_total'] else None
    return {'cases': len(cases), 'correct': len(cases) - len(errors),
            'accuracy': (len(cases) - len(errors)) / len(cases), 'families': groups,
            'contrast_pairs_total': len(pair_groups),
            'contrast_pairs_both_correct': sum(all(v) for v in pair_groups.values()),
            'errors': errors, 'medical_gold_reviewed': dataset['professional_reviewed'],
            'not_blind': dataset['not_blind'], 'clinical_correctness_verified': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, default=DEFAULT)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    validate(args.folder)
    predictions = load(args.predictions)
    require(predictions.get('version') == load(args.folder / 'dataset.json')['version'], '预测题库版本不符')
    require(bool(predictions.get('run_metadata')), '需要执行版本、实际方法及时间记录')
    result = score(load(args.folder / 'dataset.json'), predictions)
    result['run_metadata'] = predictions['run_metadata']
    from verify import digest
    result['dataset_sha256'] = digest(args.folder / 'dataset.json')
    result['predictions_sha256'] = digest(args.predictions)
    require(not args.output.exists(), '不能覆盖历史评测结果')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ['errors', 'run_metadata']}, ensure_ascii=False))
