"""实际检索工具同快照前后对照；只用缓存向量，阻断新增HTTP。"""
import asyncio
import json
import time
import logging
from contextlib import asynccontextmanager
from unittest.mock import patch,AsyncMock
import httpx
from sqlalchemy import text
from app.db.session import async_session_maker,async_engine
from app.services.embedding import EmbeddingService
from app.services.config import DynamicConfigService
from app.tools import medical
from app.services import rag
from collect import collect
from score_v2 import score,summarize


async def evaluate(payload,old):
    async_engine.echo=False;logging.disable(logging.CRITICAL)
    corpus=await collect()
    if corpus!=payload['corpus']:raise ValueError('运行语料/源码/配置不同')
    if corpus['demo_enabled']:raise ValueError('后台保护已启用，不绕过')
    if any(p['model_type']=='reranking' for p in corpus['providers']):raise ValueError('本轮不允许额外reranker调用')
    dataset=payload['dataset'];vectors=dict(zip(payload['embeddings']['queries'],payload['embeddings']['vectors']))
    if set(vectors)!={c['query'] for c in dataset['cases']}:raise ValueError('题目向量缺失或多余')
    model=payload['embeddings']['calls'][0]['model']
    docs={d['id']:d for d in corpus['documents']};chunks={c['id']:c for c in corpus['chunks']};units={u['id']:u for u in dataset['gold_units']}
    attempts=[]
    async def forbidden(*args,**kwargs):attempts.append(1);raise AssertionError('检索评测禁止额外HTTP')
    async def cached_embed(self,queries):self._model=model;return [vectors[q] for q in queries]
    groups={'before':[],'after':[]}
    current=rag.RAGService
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        @asynccontextmanager
        async def reuse_session():yield db
        import app.db.session as session_module
        with patch.object(EmbeddingService,'embed',cached_embed),patch.object(httpx.AsyncClient,'send',forbidden),patch.object(
            session_module,'async_session_maker',reuse_session),patch.object(DynamicConfigService,'external_search_enabled',AsyncMock(return_value=False)):
            for case in dataset['cases']:
                for name,implementation in [('before',old.RAGService),('after',current)]:
                    begin=time.perf_counter()
                    with patch.object(rag,'RAGService',implementation):
                        result=await medical.SearchMedicalKnowledgeTool().execute(case['query'],doc_type='platform_guideline',top_k=corpus['policy']['report_limit'])
                    sources=[]
                    for item in result['sources']:
                        anchor=chunks[item['chunk_id']];meta=item.get('context_metadata')
                        start=meta['start'] if meta else anchor['start']+anchor['content'].index(item['excerpt'])
                        end=start+len(item['excerpt'])
                        if docs[item['document_id']]['content'][start:end]!=item['excerpt']:raise ValueError('实际返回原文不同')
                        sources.append({'document_id':item['document_id'],'chunk_id':item['chunk_id'],'title':item['title'],
                            'start':start,'end':end,'excerpt':item['excerpt'],'context_metadata':meta})
                    groups[name].append({'id':case['id'],'status':'success','score':score(case,units,sources,docs),
                        'sources':sources,'serialized_sources':result['sources'],'candidate_count':result['candidate_count'],
                        'cached_internal_pipeline_ms':round((time.perf_counter()-begin)*1000,3)})
        await db.rollback()
    if attempts:raise ValueError('发生额外HTTP尝试')
    return {'mode':'actual_search_medical_knowledge_paired','read_only':True,'rolled_back':True,'network_attempts':0,
        'extra_model_calls':0,'external_search_included':False,'groups':{k:{'cases':r,'summary':summarize(dataset['cases'],r),
        'source_chars':sum(len(s['excerpt']) for row in r for s in row['sources'])} for k,r in groups.items()}}
