"""核对本次临时切换、真实向量、数据库基线与副本一致性；不访问网络/数据库。"""
import argparse
import json
from pathlib import Path
from build import read,digest
from verify import verify


def check(task):
    frozen=task/'frozen-v1'
    batch=read(task/'real-query-batch.json')
    artifact=read(task/'query-embeddings.json')
    runtime=read(task/'runtime-environment.json')
    if batch['status']!='success' or batch['restored'] is not True or batch['before']!=batch['after'] or batch['counter_unchanged'] is not True:
        raise ValueError('临时切换恢复或额度核验失败')
    if runtime['demo']!=batch['after'] or runtime['transaction_read_only']!='on':
        raise ValueError('独立只读恢复证据不一致')
    if batch['artifact']!=artifact or batch['dataset_sha256']!=digest(frozen/'dataset.json') or artifact['http_attempts']!=1 or artifact['sdk_retries']!=0:
        raise ValueError('真实向量与本次授权批次不一致')
    runs={name:verify(frozen,task/name) for name in ('postgres-smoke-v1','postgres-full-v1','sqlite-real-vectors-v1')}
    if runs['postgres-full-v1']['run_cases']!=45 or not runs['postgres-full-v1']['online_baseline_complete']:
        raise ValueError('实际数据库基线不完整')
    actual=read(task/'postgres-full-v1/results.json')
    replay=read(task/'sqlite-real-vectors-v1/results.json')
    keys=('summary','dataset_sha256','corpus_sha256','source_sha256','query_embeddings_sha256','scorer_sha256')
    if any(actual[k]!=replay[k] for k in keys):raise ValueError('实际数据库与冻结副本的输入或汇总不同')
    others={r['id']:r for r in replay['cases']}
    fields=('coarse_chunk_ids','internal_chunk_ids','score')
    for row in actual['cases']:
        other=others[row['id']]
        if any(row[k]!=other[k] for k in fields):raise ValueError('实际数据库与冻结副本逐题不一致')
        selected=lambda r:[(s['document_id'],s['chunk_id'],s['start'],s['end'],s['excerpt']) for s in r['sources']]
        if selected(row)!=selected(other):raise ValueError('最终来源顺序或摘录不一致')
    return {'status':'verified_stage2b','database_cases':45,'replay_parity_cases':45,'provider_http_attempts':1,
            'provider_calls':artifact['calls'],'recorded_protection_restored':True,'counter_unchanged':True,
            'summary':actual['summary'],'gold_clinical_review':'pending','end_to_end_consultation_complete':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',type=Path,required=True);args=parser.parse_args()
    try:
        print(json.dumps(check(args.task),ensure_ascii=False));return 0
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print(f'校验拒绝：{exc}');return 2


if __name__=='__main__':raise SystemExit(main())
