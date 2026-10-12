"""冻结实际召回结果的上下文实验；不是新的在线或PostgreSQL评测。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time
import httpx
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'evals/semantic-recall'))
from score_v2 import score,summarize
from app.services.rag_context import select_context
from app.services.knowledge_citations import build_knowledge_citations,rank_knowledge_citations
from app.services.reranker import RerankerService


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


async def main(args):
    baseline=ROOT/'.ai/tasks/2026-10-08-semantic-recall/union-final-v2/results.json'
    frozen=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    previous=read(baseline);dataset=read(frozen/'dataset.json');corpus=read(frozen/'corpus.json')
    cases=[c for c in dataset['cases'] if not args.split or c['split']==args.split]
    by_id={r['id']:r for r in previous['cases']};chunks={c['id']:c for c in corpus['chunks']}
    docs={d['id']:d for d in corpus['documents']};units={u['id']:u for u in dataset['gold_units']}
    if digest(frozen/'dataset.json')!=previous['dataset_sha256']:raise ValueError('题库指纹不同')
    if digest(frozen/'corpus.json')!=previous['corpus_sha256']:raise ValueError('原文指纹不同')
    groups={name:[] for name in ('prefix800','prefix1600','context1600')};parity=[]
    durations={name:0.0 for name in groups}
    network=AsyncMock(side_effect=AssertionError('禁止网络调用'))
    with patch.object(httpx.AsyncClient,'send',network),patch.object(RerankerService,'rerank',AsyncMock(side_effect=ValueError('冻结入口无重排供应商'))):
        for case in cases:
            original=by_id[case['id']];out={}
            for profile,budget,expanded in (('prefix800',800,False),('prefix1600',1600,False),('context1600',1600,True)):
                started=time.perf_counter()
                inputs=[];positions={}
                for cid in original['internal_chunk_ids']:
                    c=chunks[cid];d=docs[c['document_id']]
                    anchor={**c,'chunk_id':cid}
                    siblings=[{**item,'chunk_id':item['id']} for item in corpus['chunks'] if item['document_id']==c['document_id']]
                    context=select_context(case['query'],anchor,d['content'],siblings) if expanded else None
                    text,metadata=context if context else (c['content'],None)
                    positions[cid]=metadata
                    inputs.append({'source_type':'internal','title':d['title'],'document_id':c['document_id'],
                                   'chunk_id':cid,'chunk_index':c['chunk_index'],'excerpt':text,'url':d['source_url']})
                citations=build_knowledge_citations(inputs,max_excerpt_chars=budget)
                selected=(await rank_knowledge_citations(case['query'],citations,None,min_relevance=corpus['policy']['min_relevance']))[:previous['k']]
                sources=[]
                for citation in selected:
                    c=chunks[citation.chunk_id];meta=positions[citation.chunk_id]
                    if meta:
                        start=meta['start']
                        if docs[c['document_id']]['content'][start:meta['end']]!=citation.excerpt:raise ValueError('窗口坐标不符')
                    else:
                        offset=c['content'].find(citation.excerpt)
                        if offset<0:raise ValueError('旧摘录定位失败')
                        start=c['start']+offset
                    sources.append({'document_id':c['document_id'],'chunk_id':citation.chunk_id,'title':citation.title,
                        'start':start,'end':start+len(citation.excerpt),'excerpt':citation.excerpt,
                        'relevance':citation.relevance,'method':citation.relevance_method,'reason':citation.relevance_reason})
                out[profile]={'id':case['id'],'status':'success','sources':sources,'score':score(case,units,sources,docs),
                               'context_metadata':positions if expanded else None}
                durations[profile]+=time.perf_counter()-started
                groups[profile].append(out[profile])
            if out['prefix800']['sources']!=original['sources'] or out['prefix800']['score']!=original['score']:raise ValueError('旧路径重放与实际归档不一致')
            parity.append(case['id'])
    if network.call_count:raise ValueError('发生网络尝试')
    result={'mode':'frozen_retrieval_context_replay','split':args.split,
            'groups':{name:{'cases':rows,'summary':summarize(cases,rows),
                      'source_chars':sum(len(s['excerpt']) for r in rows for s in r['sources']),
                      'local_processing_ms':round(durations[name]*1000,3)} for name,rows in groups.items()},
            'prefix_parity_ids':parity,'extra_model_calls':0,'network_attempts':network.call_count,'online_or_postgres_execution':False,
            'baseline_sha256':digest(baseline),'dataset_sha256':digest(frozen/'dataset.json'),'corpus_sha256':digest(frozen/'corpus.json'),
            'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),ROOT/'backend/app/services/rag_context.py',ROOT/'backend/app/services/knowledge_citations.py',ROOT/'evals/semantic-recall/score_v2.py')},
            'profiles':{'prefix800':800,'prefix1600':1600,'context1600':1600}}
    for label,old_group,new_group in [('budget_effect','prefix800','prefix1600'),('context_effect','prefix1600','context1600'),('overall_effect','prefix800','context1600')]:
        old_rows={r['id']:r['score'] for r in groups[old_group]};rows=groups[new_group]
        positive=[(old_rows[r['id']],r['score'],r['id']) for r in rows if r['score']['complete_evidence'] is not None]
        result[label]={'improved_ids':[cid for old,new,cid in positive if new['evidence_recall_at_k']>old['evidence_recall_at_k']],
            'regressed_ids':[cid for old,new,cid in positive if new['evidence_recall_at_k']<old['evidence_recall_at_k'] or (new['qualifier_recall'] or 0)<(old['qualifier_recall'] or 0)],
            'ranking_regressed_ids':[cid for old,new,cid in positive if new['mrr']<old['mrr']],
            'new_no_answer_candidates':[r['id'] for r in rows if r['score']['unsupported_candidate_returned'] and not old_rows[r['id']]['unsupported_candidate_returned']]}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in (Path(__file__),ROOT/'backend/app/services/rag_context.py',ROOT/'backend/app/services/knowledge_citations.py'):
        (args.output/p.name).write_bytes(p.read_bytes())
    print(json.dumps({**{k:v for k,v in result.items() if k not in ('groups','prefix_parity_ids')},'groups':{name:{k:v for k,v in group.items() if k!='cases'} for name,group in result['groups'].items()}},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=['development','evaluation']);parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args()))
