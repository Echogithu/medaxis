"""离线核对三路真实召回、独立余弦与连续原文；技术探针不评分。"""
import argparse
import json
import math
import statistics
from pathlib import Path
from resume_experiment import ROOT,HERE,ASSETS,inputs,load,sha,require,write
from resume_retrieval import EVAL_FILES,payload as expected_payload
from resume_retrieval_runtime import SOURCE_PATHS,VARIANTS,validate_payload
from resume_embedding_runtime import corpus_snapshot
from resume_embedding_verify import verify_collect
from resume_eval_score import retrieval_metrics,validate_source,number,KS


def cosine(left,right):
    require(len(left)==len(right) and any(left) and any(right),'余弦向量非法')
    return sum(a*b for a,b in zip(left,right))/(math.sqrt(sum(a*a for a in left))*math.sqrt(sum(b*b for b in right)))


def validate_row(row,question,vector,model,chunks,docs):
    require(set(row)=={'id','variant','status','error_type','anchors','raw_sources','context_sources','search_ms','context_ms'}
            and row['id']==question['id'] and row['variant'] in VARIANTS and row['status']=='success' and row['error_type'] is None,'逐题检索字段/状态非法')
    for key in ('search_ms','context_ms'):number(row[key],key)
    anchors=row['anchors'];require(isinstance(anchors,list) and len(anchors)<=10 and len({a['chunk_id'] for a in anchors})==len(anchors),'锚点重复/超K')
    mandatory={'chunk_id','document_id','chunk_index','content','rank'};metadata={'retrieval_model','retrieval_dimension','retrieval_score'}
    for anchor in anchors:
        require(set(anchor)==(mandatory if row['variant']=='keyword' else mandatory|metadata),'锚点元信息缺失或多余')
        require(anchor['chunk_id'] in chunks,'锚点不在冻结索引')
        chunk=chunks[anchor['chunk_id']]
        require(all(anchor[k]==chunk[k] for k in ('document_id','chunk_index','content')),'锚点身份/内容不同')
        require(type(anchor['chunk_index']) is int and anchor['chunk_index']>=0
                and type(anchor['rank']) in (int,float) and math.isfinite(anchor['rank']),'锚点位置/排名分非法')
        if row['variant']=='keyword':require(anchor['rank']==0,'纯关键词伪装向量分')
        else:
            score=cosine(vector,chunk['embedding_json'])
            require(anchor['retrieval_model']==model and anchor['retrieval_dimension']==len(vector)
                    and type(anchor['retrieval_score']) in (int,float) and math.isfinite(anchor['retrieval_score'])
                    and math.isclose(score,anchor['retrieval_score'],abs_tol=1e-8)
                    and math.isclose(round(score,4),anchor['rank'],abs_tol=1e-8),'实际余弦/模型/维度不符')
    if row['variant']=='semantic':
        ranked=sorted(chunks.values(),key=lambda c:(-cosine(vector,c['embedding_json']),c['id']))[:10]
        require([a['chunk_id'] for a in anchors]==[c['id'] for c in ranked],'纯语义不是同模型精确top10')
    from app.services.rag_context import select_context
    projected={'raw_sources':[],'context_sources':[]}
    for anchor in anchors:
        document=docs[anchor['document_id']]['content'];body=anchor['content']
        require(document.count(body)==1,'锚点原文位置不唯一')
        start=document.index(body)
        source={'document_id':anchor['document_id'],'start':start,'end':start+len(body),'quote':body}
        siblings=[{'chunk_id':c['id'],**{k:c[k] for k in ('document_id','chunk_index','content')}} for c in chunks.values()]
        selected=select_context(question['query'],anchor,document,siblings)
        context=source if not selected else {'document_id':anchor['document_id'],'start':selected[1]['start'],'end':selected[1]['end'],'quote':selected[0]}
        for key,item in (('raw_sources',source),('context_sources',context)):
            if item not in projected[key]:projected[key].append(item)
    for key in projected:
        require(row[key]==projected[key],'原始片段/上下文窗口/顺序不符')
        for source in row[key]:validate_source(source,docs)


def summarize(results):
    positive=[r for r in results if r['answerable']];negative=[r for r in results if not r['answerable']]
    require(len(positive)==20 and len(negative)==4,'开发集评分分母变化')
    summary={'at_k':{},'source_chars':sum(r['source_chars'] for r in results)}
    for k in KS:
        key=str(k);avg=lambda name:sum(r['at_k'][key][name] for r in positive)/len(positive)
        summary['at_k'][key]={'hit_at_k':avg('hit'),'annotated_evidence_recall_at_k':avg('annotated_evidence_recall'),
                             'complete_evidence_rate':avg('complete_evidence'),'necessary_claim_coverage_rate':avg('necessary_claim_coverage'),
                             'mrr_at_k':avg('mrr'),'no_answer_false_retrieval_rate':sum(r['at_k'][key]['unsupported_returned'] for r in negative)/len(negative)}
    return summary


def verify(folder):
    folder=folder.resolve();folder.relative_to(HERE.resolve())
    execution=load(folder/'execution.json');value=load(folder/'execution-input.json');raw=load(folder/'observations-raw.json');reference=load(folder/'references.json')
    validate_payload(value);mode=value['mode']
    require(set(reference)=={'preflight','vector_run','vector_plan'},'运行来源字段非法')
    expected=expected_payload(mode,Path(reference['preflight']),Path(reference['vector_run']) if reference['vector_run'] else None,
                              Path(reference['vector_plan']) if reference['vector_plan'] else None)
    require(value==expected and execution['input_sha256']==sha((folder/'execution-input.json').read_bytes())
            and execution['references_sha256']==sha((folder/'references.json').read_bytes()),'检索输入/真实向量来源漂移')
    require(execution['docker_exit_code']==0 and not execution['timed_out'] and execution['additional_model_http_requests']==0
            and raw['complete'] is True and raw['protocol']==value['protocol'] and raw['mode']==mode
            and raw['top_k']==10 and raw['input_sha256']==value['input_sha256'] and raw['source_sha256']==value['source_sha256']
            and raw['model_snapshot']==value['expected_snapshot'] and raw['vector_evidence_sha256']==value['vector_evidence_sha256'],'运行未完整成功/实际范围不同')
    require(raw['read_only'] is True and raw['rolled_back'] is True and raw['read_gold'] is False and raw['holdout_loaded'] is False
            and raw['settings_before']==raw['settings_after'] and raw['counts']['forbidden_http']==raw['counts']['unexpected_model']==0
            and not any(raw[k] for k in ('reranking_executed','coverage_model_executed','external_search_executed','full_production_pipeline')),'检索实验门禁失败')
    for name in SOURCE_PATHS:require(sha((folder/'source'/name).read_bytes())==value['source_sha256'][name],'检索业务源码快照变化')
    for name in EVAL_FILES:require(sha((folder/name).read_bytes())==execution['evaluation_sha256'][name]==sha(Path(__file__).with_name(name).read_bytes()),'检索实验/评分规则换版')
    corpus=corpus_snapshot(raw['vector_corpus'],raw['model_snapshot']['model'])
    require(all(raw['model_snapshot'][k]==v for k,v in corpus.items()),'实际存储向量指纹不同')
    events=[json.loads(line) for line in (folder/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(events and set(events[0])=={'runtime_started'} and type(events[0]['runtime_started']['pid']) is int
            and events[0]['runtime_started']['pid']>0 and events[0]['runtime_started']['purpose']=='retrieval_ablation'
            and events[1:]==[{'checkpoint':r} for r in raw['rows']]+[{'final':raw}],'检索逐题日志与最终记录不同')
    if mode=='preflight':
        probe=raw['technical_probe']
        require(raw['rows']==[] and value['vectors'] is None and probe['purpose']=='index_self_match_pipeline_only'
                and probe['query_is_evaluation_question'] is False and probe['query_embedding_generated'] is False
                and probe['retrieval_metrics'] is None and 0<probe['semantic_anchor_count']<=10 and 0<probe['hybrid_anchor_count']<=10
                and type(probe['self_similarity']) in (int,float) and math.isclose(probe['self_similarity'],1,abs_tol=1e-8)
                and raw['counts']['cached_embedding']==1 and raw['counts']['keyword_embedding_disabled']==0
                and raw['counts']['reranking_disabled']==1,'技术探针不可变成真实语义成绩')
        return {'status':'PASS_REAL_RETRIEVAL_PIPELINE_PREFLIGHT_ONLY','model_snapshot':raw['model_snapshot'],
                'technical_probe':probe,'additional_model_http_requests':0,'retrieval_metrics':None,'clinical_accuracy':None,'policy':raw['policy']}
    require(raw['technical_probe'] is None and len(raw['rows'])==72,'正式检索缺失/混入技术探针')
    from build_resume_eval import validate
    validate(ASSETS)
    questions,_=inputs();lookup={q['id']:q for q in questions};vectors=dict(zip((q['id'] for q in value['questions']),value['vectors']))
    keys=[(r['id'],r['variant']) for r in raw['rows']]
    require(len(keys)==len(set(keys)) and set(keys)=={(qid,v) for qid in lookup for v in VARIANTS},'检索结果缺失/重复/额外')
    chunks={c['id']:c for c in raw['vector_corpus']};docs={d['id']:d for d in load(ASSETS/'corpus.json')['documents']}
    gold={q['id']:q for q in load(ASSETS/'gold.json')['questions'] if q['split']=='development'}
    groups={};per_question=[]
    for row in raw['rows']:
        q=lookup[row['id']];validate_row(row,q,vectors[q['id']],raw['model_snapshot']['model'],chunks,docs)
        g=gold[q['id']];full=next((s for s in q['candidates'] if s['id']==g['full_source_id']),None)
        for suffix,field in (('raw','raw_sources'),('context','context_sources')):
            name=row['variant']+'_'+suffix;at_k,mrr=retrieval_metrics(g,row[field],docs,full,False)
            result={'id':q['id'],'variant':name,'answerable':g['answerable'],'at_k':at_k,'mrr_all_returned':mrr,
                    'source_chars':sum(len(s['quote']) for s in row[field])}
            groups.setdefault(name,[]).append(result);per_question.append(result)
    expected_rerank=sum(bool(r['anchors']) for r in raw['rows'] if r['variant'] in {'keyword','hybrid'})
    require(raw['counts']['keyword_embedding_disabled']==raw['counts']['cached_embedding']==24
            and raw['counts']['reranking_disabled']==expected_rerank,'实际检索分支计数不同')
    embedding=verify_collect(Path(reference['vector_run']),Path(reference['vector_plan']))
    return {'status':'VERIFIED_ACTUAL_RETRIEVAL_ABLATION','queries':24,'search_rows':72,'answerable':20,'no_answer':4,
            'groups':{name:summarize(results) for name,results in groups.items()},'per_question':per_question,
            'cached_search_ms_median':{v:statistics.median(r['search_ms'] for r in raw['rows'] if r['variant']==v) for v in VARIANTS},
            'context_ms_median':statistics.median(r['context_ms'] for r in raw['rows']),
            'metric_scope':'keyword_semantic_hybrid_raw_and_context_no_rerank',
            'query_embedding_usage_once':embedding['native_usage'],'query_embedding_http_requests_once':embedding['http_requests'],
            'additional_model_http_requests':0,'clinical_accuracy':None,'candidate_accuracy':None,'full_production_pipeline':False,
            'policy':raw['policy'],'input_sha256':value['input_sha256']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=verify(args.run)
    if args.output:write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='per_question'},ensure_ascii=False))
