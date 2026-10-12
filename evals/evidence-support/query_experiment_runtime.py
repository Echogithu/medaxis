"""只读数据库配对实验；执行器仅收冻结输入，不收gold或请求覆盖金标。"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from openai import DefaultAsyncHttpxClient
from sqlalchemy import text
from app.db.session import async_engine, async_session_maker
from app.services.knowledge_citations import KnowledgeCitation, rank_knowledge_citations
from app.services.llm import LLMService
from app.services.query_requirements import assess_query, rank_assessed


async def settings(db):
    rows = await db.execute(text("SELECT key,value FROM system_settings WHERE key IN ('interview_demo.enabled','interview_demo.limit','interview_demo.used')"))
    return {r[0]: r[1] for r in rows}


async def evaluate(payload):
    async_engine.echo = False
    logging.disable(logging.CRITICAL)
    started = datetime.now(timezone.utc).isoformat()
    hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in payload['source_sha256']}
    if hashes != payload['source_sha256']:
        raise ValueError('容器源码与实验起点不同')
    requests, groups, verified = [], [], set()
    # SDK可能使用httpx2；从实际客户端类取send，不假定其底层是httpx。
    original_send = DefaultAsyncHttpxClient.send
    phase = 'before'

    async def observed_send(client, *args, **kwargs):
        if phase != 'assessment' or len(requests) >= len(payload['groups']):
            raise ValueError('禁止当前排序新增HTTP或实验超预算')
        record = {'status_code': None, 'native_usage': None, 'model': None}
        requests.append(record)
        response = await original_send(client, *args, **kwargs)
        record['status_code'] = response.status_code
        data = response.json()
        if isinstance(data, dict):
            record['model'] = data.get('model')
            usage = data.get('usage')
            if isinstance(usage, dict):
                # 只保存供应商原生计量字段，不记录请求头、URL、密钥或其他响应。
                record['native_usage'] = {k: v for k, v in usage.items()
                                         if k.endswith('tokens') and type(v) is int and v >= 0}
        return response

    try:
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            before = await settings(db)
            if before.get('interview_demo.enabled', 'false') != 'false':
                raise ValueError('演示保护已开启；停止实验，不改配置')
            configs = [dict(row) for row in (await db.execute(text(
                'SELECT provider,platform,model_type,default_model,is_default FROM llm_provider_configs WHERE is_active = true ORDER BY model_type,provider'
            ))).mappings()]
            if any(c['model_type'] == 'reranking' for c in configs):
                raise ValueError('重排配置已变化，停止沿用旧基线')
            documents = {str(d['id']): dict(d) for d in (await db.execute(text(
                "SELECT id,title,content,source_url FROM documents WHERE is_active AND doc_type='platform_guideline'"
            ))).mappings()}
            for group in payload['groups']:
                for item in group['cases']:
                    source = item['candidate_source']
                    doc = documents[source['document_id']]
                    if (hashlib.sha256(doc['content'].encode()).hexdigest() != source['document_sha256']
                        or doc['content'][source['start']:source['end']] != source['quote']
                        or doc['title'] != source['title'] or doc['source_url'] != source['source_url']):
                        raise ValueError('候选与当前库原文/出处不符')
                    verified.add(source['id'])
            service = LLMService(db=db, platform='web', model_type='diagnosis', timeout=60, max_retries=0)
            DefaultAsyncHttpxClient.send = observed_send
            for group in payload['groups']:
                candidates = [KnowledgeCitation(citation_id=f'S{i + 1}', source_type='internal',
                    title=item['candidate_source']['title'], excerpt=item['candidate_source']['quote'],
                    document_id=item['candidate_source']['document_id'], url=item['candidate_source']['source_url'])
                    for i, item in enumerate(group['cases'])]
                ids = {citation.citation_id: item['id'] for citation, item in zip(candidates, group['cases'])}
                phase = 'before'
                tick = time.perf_counter()
                current = await rank_knowledge_citations(group['query'], candidates, db)
                current_ms = round((time.perf_counter() - tick) * 1000, 3)
                before_order = [ids[c.citation_id] for c in current]
                phase = 'assessment'
                initial_count = len(requests)
                assessment = await assess_query(group['query'], [
                    {'id': item['id'], 'title': c.title, 'excerpt': c.excerpt}
                    for item, c in zip(group['cases'], candidates)], service)
                groups.append({'id': group['id'], 'query': group['query'],
                    'case_ids': [item['id'] for item in group['cases']],
                    'before_order': before_order, 'before_sources': [c.model_dump() for c in current],
                    'before_ms': current_ms, 'assessment': assessment, 'after_order': rank_assessed(assessment),
                    'http_attempts': len(requests) - initial_count})
                if assessment['status'] != 'assessed':
                    break
            after = await settings(db)
            await db.rollback()
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            outside = await settings(db)
            await db.rollback()
    finally:
        DefaultAsyncHttpxClient.send = original_send
    return {'protocol': 'query_requirements_paired_v2', 'version': payload['version'],
            'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'source_sha256': hashes, 'settings_before': before, 'settings_after': outside,
            'settings_unchanged': before == after == outside, 'read_only': True, 'rolled_back': True,
            'providers_without_credentials': configs, 'requests': requests, 'groups': groups,
            'requested_groups': len(payload['groups']), 'database_spans_verified': len(verified),
            'read_gold': False, 'vector_retrieval_executed': False, 'external_search_executed': False,
            'clinical_correctness_verified': False, 'money_cost': None}
