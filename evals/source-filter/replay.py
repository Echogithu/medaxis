"""复用真实查询向量与冻结召回，比较筛选前后；不新增检索/模型/数据库调用。"""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'evals/semantic-recall'))
from score_v2 import score,summarize
from app.services.rag import _safe_similarity
from app.services.rag_context import select_context
from app.services.knowledge_citations import build_knowledge_citations,rank_knowledge_citations
from app.services.reranker import RerankerService


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def changes(before,after):
    old={r['id']:r['score'] for r in before}
    result={k:[] for k in ('improved','coverage_regressed','ranking_regressed','no_answer_improved','no_answer_regressed')}
    for row in after:
        a,b,cid=old[row['id']],row['score'],row['id']
        if b['complete_evidence'] is None:
            if a['unsupported_candidate_returned'] and not b['unsupported_candidate_returned']:result['no_answer_improved'].append(cid)
            if b['unsupported_candidate_returned'] and not a['unsupported_candidate_returned']:result['no_answer_regressed'].append(cid)
        else:
            if b['evidence_recall_at_k']>a['evidence_recall_at_k']:result['improved'].append(cid)
            if b['evidence_recall_at_k']<a['evidence_recall_at_k'] or (b['qualifier_recall'] or 0)<(a['qualifier_recall'] or 0):result['coverage_regressed'].append(cid)
            if b['mrr']<a['mrr']:result['ranking_regressed'].append(cid)
    return result


async def main(args):
    frozen=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    dataset,corpus=read(frozen/'dataset.json'),read(frozen/'corpus.json')
    baseline=ROOT/'.ai/tasks/2026-10-08-rag-context/full-final/results.json'
    prior=read(baseline)
    embeddings=ROOT/'.ai/tasks/2026-10-07-rag-baseline/query-embeddings.json'
    artifact=read(embeddings)
    if artifact['queries']!=[c['query'] for c in dataset['cases']] or len(artifact['vectors'])!=len(dataset['cases']):raise ValueError('真实向量与题目不一致')
    if digest(frozen/'corpus.json')!=prior['corpus_sha256'] or digest(frozen/'dataset.json')!=prior['dataset_sha256']:raise ValueError('输入漂移')
    models={c['model'] for c in artifact['calls']}
    if len(models)!=1:raise ValueError('查询模型不唯一')
    model=next(iter(models));vectors=dict(zip(artifact['queries'],artifact['vectors']))
    docs={d['id']:d for d in corpus['documents']};chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']}
    cases=[c for c in dataset['cases'] if not args.split or c['split']==args.split]
    recall=read(ROOT/'.ai/tasks/2026-10-08-semantic-recall/union-final-v2/results.json')
    recalled={r['id']:r for r in recall['cases']}
    groups={name:[r for r in prior['groups'][key]['cases'] if r['id'] in {c['id'] for c in cases}]
            for name,key in [('original800','prefix800'),('context_before','context1600')]}
    groups.update(filtered800=[],filtered_context=[])
    network=AsyncMock(side_effect=AssertionError('禁止新增模型与外部调用'))
    with patch.object(httpx.AsyncClient,'send',network),patch.object(RerankerService,'rerank',AsyncMock(side_effect=ValueError('无供应商'))):
        for case in cases:
            for profile,expanded in [('filtered800',False),('filtered_context',True)]:
                inputs=[];positions={}
                q=vectors[case['query']]
                for cid in recalled[case['id']]['internal_chunk_ids']:
                    c=chunks[cid];d=docs[c['document_id']]
                    anchor={**c,'chunk_id':cid}
                    siblings=[{**item,'chunk_id':item['id']} for item in corpus['chunks'] if item['document_id']==c['document_id']]
                    context=select_context(case['query'],anchor,d['content'],siblings) if expanded else None
                    excerpt,meta=context if context else (c['content'],None)
                    positions[cid]=meta
                    similarity=_safe_similarity(q,c['embedding_json']) if d['embedding_model']==model else None
                    inputs.append({'source_type':'internal','title':d['title'],'document_id':c['document_id'],
                        'chunk_id':cid,'chunk_index':c['chunk_index'],'excerpt':excerpt,'source_url':d['source_url'],
                        'context_metadata':meta,'retrieval_method':'embedding_cosine' if similarity is not None else 'keyword',
                        'retrieval_model':model if similarity is not None else None,'retrieval_score':similarity,
                        'retrieval_dimension':len(q) if similarity is not None else None,
                        'retrieval_anchor_excerpt':c['content'].strip()[:800],
                        'retrieval_query_fingerprint':hashlib.sha256(case['query'].strip()[:512].encode()).hexdigest()})
                citations=build_knowledge_citations(inputs,max_excerpt_chars=1600 if expanded else 800)
                ranked=(await rank_knowledge_citations(case['query'],citations,None,min_relevance=corpus['policy']['min_relevance']))[:recall['k']]
                sources=[]
                for citation in ranked:
                    original=chunks[citation.chunk_id]
                    if citation.context_metadata:
                        start=citation.context_metadata['start']
                    else:
                        start=original['start']+original['content'].index(citation.excerpt)
                    sources.append({'document_id':citation.document_id,'chunk_id':citation.chunk_id,'title':citation.title,
                        'start':start,'end':start+len(citation.excerpt),'excerpt':citation.excerpt,
                        'relevance':citation.relevance,'method':citation.relevance_method,'reason':citation.relevance_reason,
                        'retrieval_score':citation.retrieval_score,'retrieval_model':citation.retrieval_model,
                        'context_metadata':citation.context_metadata})
                groups[profile].append({'id':case['id'],'status':'success','sources':sources,'score':score(case,units,sources,docs)})
    if network.call_count:raise ValueError('发生网络尝试')
    result={'mode':'frozen_recall_relevance_experiment','split':args.split,'requested_ids':[c['id'] for c in cases],
        'baseline_sha256':digest(baseline),'dataset_sha256':digest(frozen/'dataset.json'),'corpus_sha256':digest(frozen/'corpus.json'),
        'query_embeddings_sha256':digest(embeddings),'extra_model_calls':0,'network_attempts':network.call_count,
        'online_or_postgres_execution':False,'k':recall['k'],
        'groups':{name:{'cases':rows,'summary':summarize(cases,rows),'source_chars':sum(len(s['excerpt']) for r in rows for s in r['sources'])} for name,rows in groups.items()},
        'filter_effect':changes(groups['context_before'],groups['filtered_context']),
        'overall_effect':changes(groups['original800'],groups['filtered_context']),
        'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),ROOT/'backend/app/services/knowledge_citations.py',ROOT/'backend/app/services/rag.py',ROOT/'backend/app/services/rag_context.py',ROOT/'evals/semantic-recall/score_v2.py',ROOT/'evals/rag-baseline/score.py')}}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in result['code_sha256']:
        p=ROOT/name
        (args.output/p.name).write_bytes(p.read_bytes())
    print(json.dumps({**{k:v for k,v in result.items() if k not in ('groups','code_sha256','requested_ids')},'groups':{k:{'summary':v['summary'],'source_chars':v['source_chars']} for k,v in result['groups'].items()}},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=['development','evaluation'])
    parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args()))
