"""在运行容器内只读冻结平台指南；可批量生成合成题的真实查询向量。"""
import argparse
import asyncio
import base64
import hashlib
import json
import math
from pathlib import Path
import sys
from sqlalchemy import text
from app.db.session import async_session_maker, async_engine
from app.services.config import DynamicConfigService
from app.core.config import get_settings


async def collect():
    async_engine.echo = False
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        docs = (await db.execute(text("SELECT id,title,content,source_url,embedding_model,updated_at,review_status FROM documents WHERE is_active AND doc_type='platform_guideline' ORDER BY id"))).mappings().all()
        chunks = (await db.execute(text("SELECT c.id,c.document_id,c.chunk_index,c.content,c.embedding_json FROM document_chunks c JOIN documents d ON d.id=c.document_id WHERE d.is_active AND d.doc_type='platform_guideline' ORDER BY c.document_id,c.chunk_index"))).mappings().all()
        providers = (await db.execute(text("SELECT id,model_type,default_model FROM llm_provider_configs WHERE is_active AND model_type IN ('embedding','reranking') ORDER BY id"))).mappings().all()
        demo = (await db.execute(text("SELECT value FROM system_settings WHERE key='interview_demo.enabled'"))).scalar()
        policy = await DynamicConfigService.knowledge_source_policy(db)
        policy['report_limit'] = await DynamicConfigService.diagnosis_report_source_limit(db)
        await db.rollback()
    config = get_settings()
    policy.update(coarse_multiplier=config.rag_coarse_multiplier, coarse_min=config.rag_coarse_min,
                  query_term_length=config.rag_query_term_length)
    documents = [{**dict(r), 'id':str(r['id']), 'updated_at':r['updated_at'].isoformat(),
                  'text_sha256':hashlib.sha256(r['content'].encode()).hexdigest()} for r in docs]
    by_id = {d['id']:d for d in documents}
    offsets = {}
    records = []
    for row in chunks:
        r = dict(row)
        did = str(r['document_id'])
        start = by_id[did]['content'].find(r['content'], offsets.get(did, 0))
        if start < 0:
            raise ValueError('片段无法定位到文档原文，停止冻结')
        offsets[did] = start + 1
        vector = r['embedding_json']
        if isinstance(vector, str):
            vector = json.loads(vector)
        if not vector or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector):
            raise ValueError('片段缺少有效向量')
        records.append({**r,'id':str(r['id']),'document_id':did,'embedding_json':vector,
                        'start':start,'end':start+len(r['content'])})
    source = Path(__import__('app').__file__).resolve().parent
    hashes = {p.relative_to(source.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(source.rglob('*.py'))}
    return {'mode':'readonly_platform_guideline_snapshot','documents':documents,'chunks':records,
            'providers':[{**dict(r),'id':str(r['id'])} for r in providers],
            'demo_enabled':demo not in (None,'false'), 'policy':policy,'source_sha256':hashes}


async def embeddings(encoded, single_attempt=False):
    from app.services.embedding import EmbeddingService
    from app.services.interview_demo import load_policy
    async_engine.echo = False
    queries = json.loads(base64.b64decode(encoded).decode('utf-8'))
    if not isinstance(queries,list) or not 1<=len(queries)<=60 or any(not isinstance(q,str) or not q.strip() or len(q)>300 for q in queries):
        raise ValueError('查询批次格式或预算无效')
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        if (await load_policy(db)).enabled:
            raise RuntimeError('演示保护已启用，后台评估不得绕过身份或额度')
        svc = EmbeddingService(db)
        client = await svc._get_client()
        if single_attempt:
            client.max_retries = 0
        original = client.embeddings.create
        observations = []
        attempts = []
        async def count_attempt(_request):
            attempts.append(1)
        client._client.event_hooks['request'].append(count_attempt)
        async def observe(**kwargs):
            response = await original(**kwargs)
            observations.append({'model':response.model, 'usage':response.usage.model_dump()})
            if [item.index for item in response.data] != list(range(len(queries))):
                raise ValueError('供应商向量序号与输入顺序不一致')
            return response
        client.embeddings.create = observe
        try:
            vectors = await svc.embed(queries)
        finally:
            await db.rollback()
            await client.close()
    if len(vectors)!=len(queries):
        raise ValueError('供应商返回缺失向量')
    return {'mode':'real_provider_query_embeddings','queries':queries,'vectors':vectors,'calls':observations,
            'http_attempts':len(attempts),'sdk_retries':0 if single_attempt else 2}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--queries-base64')
    args=parser.parse_args()
    try:
        result=asyncio.run(embeddings(args.queries_base64) if args.queries_base64 else collect())
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__},ensure_ascii=False))
        return 1


if __name__=='__main__':
    sys.exit(main())
