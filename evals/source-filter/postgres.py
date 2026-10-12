"""在Docker内执行原路径与真实问诊检索工具；同一只读快照、缓存真实向量、禁止网络。"""
import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock,patch
from sqlalchemy import text
from app.db.session import async_engine,async_session_maker
from app.services.embedding import EmbeddingService
from app.services.rag import RAGService
from app.services.config import DynamicConfigService
from app.tools.medical import SearchMedicalKnowledgeTool
from app.models.rag import DocType
from collect import collect
from score_v2 import score,summarize


class ReadOnlyDb:
    def __init__(self,session):self.session=session
    async def execute(self,statement):return await self.session.execute(statement)
    async def stream(self,statement):return await self.session.stream(statement)
    def begin_nested(self):return self.session.begin_nested()


async def main(payload,old_rag,old_citations):
    async_engine.echo=False;logging.disable(logging.CRITICAL)
    corpus,dataset=payload['corpus'],payload['dataset']
    if await collect()!=corpus:raise ValueError('当前数据库/源码/政策不同，拒绝混用')
    if any(p['model_type']=='reranking' for p in corpus['providers']):raise ValueError('实际入口不能新增重排调用')
    artifact=payload['embeddings']
    if artifact['queries']!=[c['query'] for c in dataset['cases']]:raise ValueError('缓存向量与题目不同')
    vectors=dict(zip(artifact['queries'],artifact['vectors']))
    docs={d['id']:d for d in corpus['documents']};chunks={c['id']:c for c in corpus['chunks']}
    units={u['id']:u for u in dataset['gold_units']}
    old_rows={r['id']:r for r in payload['stage3']['cases']}
    offline={r['id']:r for r in payload['offline']['groups']['filtered_context']['cases']}
    cases=[c for c in dataset['cases'] if c['id'] in payload['ids']]
    calls=[]
    async def forbidden(*args,**kwargs):
        calls.append(1);raise AssertionError('本次检索禁止新增网络')
    async def cached_embed(self,texts):
        self._model=artifact['calls'][0]['model'];return [vectors[q] for q in texts]
    groups={'before':[],'after':[]}
    import httpx
    import app.db.session as session_module
    async with async_session_maker() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        db=ReadOnlyDb(session)
        @asynccontextmanager
        async def reuse_session():yield db
        with patch.object(EmbeddingService,'embed',cached_embed),patch.object(httpx.AsyncClient,'send',forbidden),patch.object(
            session_module,'async_session_maker',reuse_session),patch.object(DynamicConfigService,'external_search_enabled',AsyncMock(return_value=False)):
            for case in cases:
                q=case['query']
                for profile in ('before','after'):
                    begin=time.perf_counter()
                    if profile=='before':
                        retrieved=await old_rag.RAGService(db).search(q,doc_type=DocType.PLATFORM_GUIDELINE,top_k=corpus['policy']['internal_candidates'])
                        raw=[{'source_type':'internal','title':c['document_title'],'document_id':c['document_id'],
                            'chunk_id':c['chunk_id'],'chunk_index':c['chunk_index'],'excerpt':c['content'],'source_url':c.get('source_url')} for c in retrieved]
                        citations=old_citations.build_knowledge_citations(raw)
                        selected=(await old_citations.rank_knowledge_citations(q,citations,db,min_relevance=corpus['policy']['min_relevance']))[:corpus['policy']['report_limit']]
                        serialized=[c.model_dump() for c in selected]
                    else:
                        result=await SearchMedicalKnowledgeTool().execute(q,doc_type='platform_guideline',top_k=corpus['policy']['report_limit'])
                        serialized=result['sources']
                        if result['external_sources']!=0:raise ValueError('纯内部测试出现外部来源')
                    sources=[]
                    for item in serialized:
                        c=chunks[item['chunk_id']];meta=item.get('context_metadata')
                        start=meta['start'] if meta else c['start']+c['content'].index(item['excerpt'])
                        end=start+len(item['excerpt'])
                        if docs[c['document_id']]['content'][start:end]!=item['excerpt']:raise ValueError('真实来源坐标不符')
                        if meta and (meta['end']!=end or meta['source_text_sha256']!=docs[c['document_id']]['text_sha256']):raise ValueError('真实定位元信息不符')
                        source={'document_id':item['document_id'],'chunk_id':item['chunk_id'],'title':item['title'],
                            'start':start,'end':end,'excerpt':item['excerpt'],'relevance':item['relevance'],
                            'method':item['relevance_method'],'reason':item['relevance_reason']}
                        if profile=='after':source.update(retrieval_score=item['retrieval_score'],retrieval_model=item['retrieval_model'],context_metadata=meta)
                        sources.append(source)
                    row={'id':case['id'],'status':'success','sources':sources,'score':score(case,units,sources,docs),
                         'cached_internal_pipeline_ms':round((time.perf_counter()-begin)*1000,3),'serialized_sources':serialized}
                    expected=old_rows[case['id']] if profile=='before' else offline[case['id']]
                    if sources!=expected['sources'] or row['score']!=expected['score']:raise ValueError('真实入口与相同输入归档不一致：'+case['id']+'/'+profile)
                    groups[profile].append(row)
        await session.rollback()
    if calls:raise ValueError('尝试了新增网络')
    return {'mode':'postgres_real_tool_same_inputs','read_only':True,'rolled_back':True,'network_attempts':len(calls),
        'extra_model_calls':0,'external_search_included':False,'requested_ids':payload['ids'],
        'groups':{name:{'cases':rows,'summary':summarize(cases,rows),'source_chars':sum(len(s['excerpt']) for r in rows for s in r['sources'])} for name,rows in groups.items()}}
