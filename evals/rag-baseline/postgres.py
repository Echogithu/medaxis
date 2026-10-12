"""实际PostgreSQL只读检索；复用已付费真实查询向量，禁止额外网络请求。"""
import asyncio
import hashlib
import json
import logging
import math
import time
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import text
from app.db.session import async_session_maker,async_engine
from app.services.embedding import EmbeddingService
from app.services.rag import RAGService
from app.services.knowledge_citations import build_knowledge_citations,rank_knowledge_citations
from app.models.rag import DocType
from collect import collect
from build import validate
from score import score,summarize


class CapturedRows:
    def __init__(self,rows):self.rows=rows
    def all(self):return self.rows


class ReadOnlyDb:
    def __init__(self,session):
        self.session=session
        self.coarse_ids=[]
        self.sql_sha256=None
    async def execute(self,statement):
        result=await self.session.execute(statement)
        if 'document_chunks' in str(statement):
            rows=result.all()
            self.coarse_ids=[str(row.id) for row in rows]
            self.sql_sha256=hashlib.sha256(str(statement).encode()).hexdigest()
            return CapturedRows(rows)
        return result


async def execute(payload):
    async_engine.echo=False
    logging.disable(logging.CRITICAL)
    corpus,dataset=payload['corpus'],payload['dataset']
    validate(corpus,dataset)
    if await collect()!=corpus:
        raise ValueError('当前数据库、配置或源码不同，拒绝混用基线')
    if any(p['model_type']=='reranking' for p in corpus['providers']):
        raise ValueError('当前入口不额外调用重排供应商')
    artifact=payload['embeddings']
    queries=[c['query'] for c in dataset['cases']]
    if artifact['mode']!='real_provider_query_embeddings' or artifact['queries']!=queries or len(artifact['vectors'])!=len(queries):
        raise ValueError('真实向量与完整题库不对应')
    if {c['model'] for c in artifact['calls']}!={d['embedding_model'] for d in corpus['documents']}:
        raise ValueError('查询与语料向量模型不同')
    dimensions={len(c['embedding_json']) for c in corpus['chunks']}
    if len(dimensions)!=1 or any(len(v) not in dimensions or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in artifact['vectors']):
        raise ValueError('向量维度或数值无效')
    vectors=dict(zip(queries,artifact['vectors']))
    requested=payload['ids']
    cases=dataset['cases']
    if requested:
        if not set(requested)<={c['id'] for c in cases}:raise ValueError('题目ID无效')
        cases=[c for c in cases if c['id'] in requested]
    docs={d['id']:d for d in corpus['documents']}
    chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']}
    network=[]
    async def forbid_network(*_args,**_kwargs):
        network.append(1)
        raise AssertionError('检索重放禁止额外网络调用')
    async def cached_embed(_self,texts):return [vectors[q] for q in texts]
    def original_sources(ids):
        return [{'document_id':chunks[cid]['document_id'],'chunk_id':cid,'start':chunks[cid]['start'],
                 'end':chunks[cid]['end'],'excerpt':chunks[cid]['content']} for cid in ids]
    config=corpus['policy']
    rows=[]
    import httpx
    async with async_session_maker() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        db=ReadOnlyDb(session)
        with patch.object(EmbeddingService,'embed',cached_embed),patch.object(httpx.AsyncClient,'send',forbid_network):
            for case in cases:
                begin=time.perf_counter()
                db.coarse_ids=[]
                try:
                    retrieved=await RAGService(db).search(case['query'],doc_type=DocType.PLATFORM_GUIDELINE,top_k=config['internal_candidates'])
                    internal=[r['chunk_id'] for r in retrieved]
                    citations=build_knowledge_citations([{'source_type':'internal','title':r['document_title'],
                         'document_id':r['document_id'],'chunk_id':r['chunk_id'],'chunk_index':r['chunk_index'],
                         'excerpt':r['content'],'url':r['source_url']} for r in retrieved])
                    selected=(await rank_knowledge_citations(case['query'],citations,db,min_relevance=config['min_relevance']))[:config['report_limit']]
                    sources=[]
                    for citation in selected:
                        original=chunks[citation.chunk_id]
                        local=original['content'].find(citation.excerpt)
                        if local<0:raise ValueError('最终摘录不在原文片段内')
                        start=original['start']+local
                        sources.append({'document_id':citation.document_id,'chunk_id':citation.chunk_id,'title':citation.title,
                           'start':start,'end':start+len(citation.excerpt),'excerpt':citation.excerpt,
                           'relevance':citation.relevance,'method':citation.relevance_method,'reason':citation.relevance_reason})
                    if network:raise AssertionError('存在未授权额外网络请求')
                    rows.append({'id':case['id'],'family':case['family'],'split':case['split'],'status':'success',
                        'coarse_chunk_ids':db.coarse_ids[:],'coarse_sql_sha256':db.sql_sha256,'internal_chunk_ids':internal,
                        'internal_ranks':[r['rank'] for r in retrieved],'sources':sources,
                        'stage_scores':{'coarse':score(case,units,original_sources(db.coarse_ids),docs),
                                        'internal':score(case,units,original_sources(internal),docs)},
                        'score':score(case,units,sources,docs)})
                except Exception as exc:
                    rows.append({'id':case['id'],'status':'failed','error_type':type(exc).__name__})
                rows[-1]['retrieval_with_cached_query_vector_ms']=round((time.perf_counter()-begin)*1000,2)
        await session.rollback()
    if await collect()!=corpus:raise ValueError('运行期间数据库/配置/源码发生变化，基线不封存')
    groups={field:{value:summarize([c for c in cases if c[field]==value],[r for r in rows if r['id'] in {c['id'] for c in cases if c[field]==value}])
                  for value in sorted({c[field] for c in cases})} for field in ('split','family')}
    return {'mode':'postgres_original_code_cached_real_query_vectors','cases':rows,'summary':summarize(cases,rows),
            'groups':groups,'additional_network_attempts':len(network),'read_only':True,'rolled_back':True,
            'source_sha256':corpus['source_sha256'],'k':config['report_limit'],
            'online_baseline_complete':len(cases)==len(dataset['cases']) and all(r['status']=='success' for r in rows),
            'end_to_end_consultation_complete':False,'metrics_status':'provisional_gold_not_clinically_reviewed',
            'production_latency_ms':None,'provider_usage':artifact['calls']}


async def main(payload):
    try:
        result=await execute(payload)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0 if result['summary']['status']=='complete_diagnostic' else 1
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}))
        return 1
