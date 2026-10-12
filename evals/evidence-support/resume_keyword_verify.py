"""关键词实际输出离线核对与原文级评分，单列消融边界；不调用模型。"""
import argparse
import json
import statistics
from pathlib import Path
from resume_experiment import ROOT, HERE, ASSETS, load, sha, require, write, inputs
from resume_keyword import EVAL_FILES, payload as expected_payload
from resume_keyword_runtime import SOURCE_PATHS, validate_payload
from build_resume_eval import validate
from resume_eval_score import retrieval_metrics,validate_source,KS


def verify(folder):
    folder=folder.resolve();folder.relative_to(HERE.resolve())
    validate(ASSETS)
    execution=load(folder/'execution.json');payload=load(folder/'execution-input.json');raw=load(folder/'observations-raw.json')
    validate_payload(payload)
    require(payload==expected_payload() and execution['input_sha256']==sha((folder/'execution-input.json').read_bytes()),'关键词执行输入/源码漂移')
    require(execution['docker_exit_code']==0 and not execution['timed_out'] and raw['complete'],'关键词运行未完整结束')
    require(raw['mode']=='actual_keyword_fallback_context_ablation' and raw['protocol']==payload['protocol']
            and raw['input_sha256']==payload['input_sha256'] and raw['source_sha256']==payload['source_sha256'],'原始运行关联不同')
    require(raw['read_only'] and raw['rolled_back'] and raw['read_gold'] is False and raw['holdout_loaded'] is False
            and raw['counts']['forbidden_http']==raw['counts']['unexpected_model']==0
            and not any(raw[k] for k in ('embedding_executed','reranking_executed','coverage_model_executed','external_search_executed','full_production_pipeline')),'关键词消融范围或网络门禁失败')
    for name in SOURCE_PATHS:
        require(sha((folder/'source'/name).read_bytes())==payload['source_sha256'][name],'业务源码快照变化')
    for name in EVAL_FILES:
        require(sha((folder/name).read_bytes())==execution['evaluation_sha256'][name]==sha(Path(__file__).with_name(name).read_bytes()),'实验或评分规则换版')
    questions,fingerprint=inputs();lookup={q['id']:q for q in questions}
    require(raw['top_k']==10 and len(raw['rows'])==len({r['id'] for r in raw['rows']})==24
            and {r['id'] for r in raw['rows']}==set(lookup),'开发结果缺失/重复，拒绝改分母')
    events=[json.loads(line) for line in (folder/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(events==[{'checkpoint':r} for r in raw['rows']]+[{'final':raw}],'逐题记录与最终输出不同')
    docs={d['id']:d for d in load(ASSETS/'corpus.json')['documents']}
    gold={g['id']:g for g in load(ASSETS/'gold.json')['questions'] if g['split']=='development'}
    results=[];groups={}
    for row in raw['rows']:
        require(set(row)=={'id','status','error_type','anchor_chunk_ids','raw_sources','context_sources','raw_keyword_ms','context_only_ms','expanded_anchor_count'}
                and row['status']=='success' and row['error_type'] is None,'错误或额外标注字段')
        require(len(row['anchor_chunk_ids'])==len(set(row['anchor_chunk_ids']))<=10,'命中锚点重复/过量')
        g=gold[row['id']];q=lookup[row['id']]
        full=next((s for s in q['candidates'] if s['id']==g['full_source_id']),None)
        entry={'id':row['id'],'answerable':g['answerable']}
        for variant,name in (('keyword_raw','raw_sources'),('keyword_context','context_sources')):
            sources=row[name]
            require(isinstance(sources,list) and len(sources)<=len(row['anchor_chunk_ids'])
                    and len({(s['document_id'],s['start'],s['end']) for s in sources})==len(sources),'实际来源重复/过量')
            for source in sources:validate_source(source,docs)
            at_k,mrr=retrieval_metrics(g,sources,docs,full,False)
            entry[variant]={'at_k':at_k,'mrr_all_returned':mrr,'source_chars':sum(len(s['quote']) for s in sources)}
        results.append(entry)
    for variant in ('keyword_raw','keyword_context'):
        pos=[r for r in results if r['answerable']];neg=[r for r in results if not r['answerable']]
        groups[variant]={'at_k':{},'mrr_all_returned':sum(r[variant]['mrr_all_returned'] for r in pos)/len(pos),
                         'source_chars':sum(r[variant]['source_chars'] for r in results)}
        for k in KS:
            key=str(k);avg=lambda field:sum(r[variant]['at_k'][key][field] for r in pos)/len(pos)
            groups[variant]['at_k'][key]={'hit_at_k':avg('hit'),'annotated_evidence_recall_at_k':avg('annotated_evidence_recall'),
                'complete_evidence_rate':avg('complete_evidence'),'necessary_claim_coverage_rate':avg('necessary_claim_coverage'),
                'mrr_at_k':avg('mrr'),'no_answer_false_retrieval_rate':sum(r[variant]['at_k'][key]['unsupported_returned'] for r in neg)/len(neg)}
    return {'status':'VERIFIED_ACTUAL_KEYWORD_CONTEXT_ABLATION','groups_count':24,'answerable':20,'no_answer':4,
            'groups':groups,'per_question':results,'metric_scope':'keyword_fallback_raw_vs_context_only',
            'policy':raw['policy'],'model_http_requests':0,'clinical_accuracy':None,'candidate_accuracy':None,
            'full_production_pipeline':False,'input_sha256':fingerprint,
            'keyword_sql_ms_median':statistics.median(r['raw_keyword_ms'] for r in raw['rows']),
            'context_only_ms_median':statistics.median(r['context_only_ms'] for r in raw['rows']),
            'expanded_anchor_count':sum(r['expanded_anchor_count'] for r in raw['rows']),
            'limits':['同4篇语料的开发题，非盲测，专业审核0','主动禁用向量与重排，仅关键词回退消融','没有报告生成或覆盖判断，不代表完整生产链路','Recall按已标注原文主张计算，非穷尽整库相关片段']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=verify(args.run)
    if args.output:write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'per_question','limits'}},ensure_ascii=False))
