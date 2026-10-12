"""按修订映射区分同输入/金标修订/新输入，避免制造算法改善。"""
import argparse
import json
from pathlib import Path

from baseline_verify import BASELINE, verify
from revise_v4 import OUT, verify_revision
from verify import load, require


def compare():
    verify_revision()
    verify(BASELINE)
    new_run = OUT.parent / 'baseline-v4-authorized'
    verify(new_run, assets_dir=OUT)
    before = load(BASELINE / 'full/observations.json')
    after = load(new_run / 'full/observations.json')
    require(before['source_sha256'] == after['source_sha256'], '生产源码不同，不能作为零算法变更记录')
    require(before['providers_without_credentials'] == after['providers_without_credentials'], '供应商配置不同')
    require(before['settings_before'] == after['settings_before'], '保护或额度设置不同')
    old_rows = {r['id']: r for r in before['rows']}
    new_rows = {r['id']: r for r in after['rows']}
    results = []
    for row in load(OUT / 'revision-map.json')['rows']:
        observed = None
        if row['old_id'] and not row['input_changed']:
            old = {k: v for k, v in old_rows[row['old_id']].items() if k != 'elapsed_ms'}
            new = {k: v for k, v in new_rows[row['new_id']].items() if k != 'elapsed_ms'}
            observed = old == new
        results.append({**row, 'same_input_behavior_unchanged': observed})
    same_input = [r for r in results if r['same_input_behavior_unchanged'] is not None]
    return {'scope': '题库修订及重新建立基线，不是算法改善实验',
            'production_sha_equal': True, 'provider_and_settings_equal': True,
            'same_input_cases': len(same_input),
            'same_input_behavior_unchanged': sum(r['same_input_behavior_unchanged'] for r in same_input),
            'same_input_behavior_changed': sum(not r['same_input_behavior_unchanged'] for r in same_input),
            'revised_gold_only': sum(r['old_id'] is not None and not r['input_changed'] and r['old_label'] != r['new_label'] for r in results),
            'changed_input_cases': sum(r['old_id'] is not None and r['input_changed'] for r in results),
            'added_cases': sum(r['old_id'] is None for r in results),
            'overall_accuracy_improvement': None, 'rows': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = compare()
    if args.output:
        require(not args.output.exists(), '不覆盖历史对照')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False))
