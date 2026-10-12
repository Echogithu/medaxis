"""校验冻结原文、执行器指纹与逐题分数；不运行应用或连接数据库。"""
import argparse
import json
from pathlib import Path
from build import read,digest,validate
from score import score,summarize


def verify(frozen,output):
    corpus=read(frozen/'corpus.json')
    dataset=read(frozen/'dataset.json')
    result=read(output/'results.json')
    validation=validate(corpus,dataset)
    if dataset['snapshot_sha256']!=digest(frozen/'corpus.json') or result['corpus_sha256']!=digest(frozen/'corpus.json') or result['dataset_sha256']!=digest(frozen/'dataset.json'):
        raise ValueError('题库或语料指纹改变')
    if result['source_sha256']!=corpus['source_sha256']:
        raise ValueError('源码清单改变')
    for name,sha in corpus['source_sha256'].items():
        if digest(frozen/'source'/name)!=sha:
            raise ValueError('冻结应用源码改变')
    names={'build.py','score.py','replay.py','collect.py','topics.json'}
    postgres=result['mode']=='postgres_original_code_cached_real_query_vectors'
    if postgres:names.update({'postgres.py','run_postgres.py'})
    if set(result['executor_sha256'])!=names:
        raise ValueError('执行器记录不完整')
    for name in names:
        if digest(output/'executor'/name)!=result['executor_sha256'][name]:
            raise ValueError('执行器源码改变')
    runner='run_postgres.py' if postgres else 'replay.py'
    if result['runner_sha256']!=result['executor_sha256'][runner] or result['scorer_sha256']!=result['executor_sha256']['score.py']:
        raise ValueError('执行器与评分器记录不一致')
    # 若量尺已更新，拒绝用新规则悄悄重评历史成绩。
    if digest(Path(__file__).with_name('score.py'))!=result['scorer_sha256']:
        raise ValueError('当前量尺与历史量尺不同，请恢复记录的版本后校验')
    by_id={c['id']:c for c in dataset['cases']}
    docs={d['id']:d for d in corpus['documents']}
    units={u['id']:u for u in dataset['gold_units']}
    if result['query_embeddings_sha256'] is not None:
        if digest(output/'query-embeddings.json')!=result['query_embeddings_sha256']:
            raise ValueError('真实查询向量文件改变')
        artifact=read(output/'query-embeddings.json')
        if artifact['queries']!=[c['query'] for c in dataset['cases']] or len(artifact['queries'])!=len(artifact['vectors']):
            raise ValueError('真实向量与完整题库不对应')
        if result['provider_usage']!=artifact['calls']:
            raise ValueError('供应商用量记录不一致')
    rows=result['cases']
    selected=[]
    for row in rows:
        case=by_id[row['id']]
        selected.append(case)
        if row['status']=='success' and row['score']!=score(case,units,row['sources'],docs):
            raise ValueError('逐题分数与原始摘录不一致')
        if postgres and row['status']=='success':
            chunks={c['id']:c for c in corpus['chunks']}
            for stage,field in (('coarse','coarse_chunk_ids'),('internal','internal_chunk_ids')):
                sources=[{'document_id':chunks[cid]['document_id'],'start':chunks[cid]['start'],
                          'end':chunks[cid]['end'],'excerpt':chunks[cid]['content']} for cid in row[field]]
                if row['stage_scores'][stage]!=score(case,units,sources,docs):
                    raise ValueError('检索阶段分数不一致')
    actual=summarize(selected,rows)
    if actual!=result['summary']:
        raise ValueError('汇总分数与逐题结果不一致')
    if postgres and (not result['read_only'] or not result['rolled_back'] or result['additional_network_attempts']!=0
                     or result['online_baseline_complete']!=(len(selected)==len(dataset['cases']) and actual['status']=='complete_diagnostic')):
        raise ValueError('实际数据库入口的完成或只读状态不一致')
    for field in ('split','family'):
        values=sorted({c[field] for c in selected})
        if set(result['groups'][field])!=set(values):
            raise ValueError('分组记录不完整')
        for value in values:
            subset=[c for c in selected if c[field]==value]
            ids={c['id'] for c in subset}
            if result['groups'][field][value]!=summarize(subset,[r for r in rows if r['id'] in ids]):
                raise ValueError('分组分数不一致')
    return {'status':'verified_artifact','dataset':validation,'run_cases':len(rows),'summary':actual,
            'clinical_review_status':'pending','online_baseline_complete':result['online_baseline_complete']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=verify(args.frozen,args.output)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['summary']['status']=='complete_diagnostic' else 1
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print(f'校验拒绝：{exc}')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
