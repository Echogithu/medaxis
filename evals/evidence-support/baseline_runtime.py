"""Docker内直接调用现有生产判别入口，仅接收inputs，不读取gold。"""
import hashlib
import logging
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from app.db.session import async_engine, async_session_maker
from app.services.knowledge_citations import KnowledgeCitation, attach_knowledge_citations, rank_knowledge_citations

SOURCE_PATHS = ['app/services/rag.py', 'app/services/knowledge_citations.py',
                'app/services/rag_context.py', 'app/services/orchestrator.py', 'app/services/reranker.py']


async def settings(db):
    result = await db.execute(text("SELECT key,value FROM system_settings WHERE key IN ('interview_demo.enabled','interview_demo.limit','interview_demo.used')"))
    return {row[0]: row[1] for row in result}


async def evaluate(payload):
    async_engine.echo = False
    logging.disable(logging.CRITICAL)
    begin = datetime.now(timezone.utc).isoformat()
    rows = []
    network_attempts = []
    original_send = httpx.AsyncClient.send
    async def observed_send(client, *args, **kwargs):
        # 仅计数，仍调用原传输；不记录URL、请求头或正文，不伪造供应商结果。
        network_attempts.append(1)
        return await original_send(client, *args, **kwargs)
    httpx.AsyncClient.send = observed_send
    hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in SOURCE_PATHS}
    for name, expected in payload['expected_production_sha256'].items():
        if hashes[name] != expected:
            raise ValueError('容器实际源码与冻结版本不一致：' + name)
    # 只记录非凭证配置字段；不序列化ORM对象/API key/base_url。
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        before = await settings(db)
        configs = [dict(row) for row in (await db.execute(text(
            'SELECT provider,platform,model_type,default_model,is_default FROM llm_provider_configs WHERE is_active = true ORDER BY model_type,provider'
        ))).mappings()]
        # 既有环境无reranker；配置漂移时停止，不能假造失败强制词匹配或不加说明扩大发送。
        if any(c['model_type'] == 'reranking' for c in configs):
            raise ValueError('检测到新增reranking配置，请先核对新运行协议与成本')
        documents = {str(d['id']): dict(d) for d in (await db.execute(text(
            "SELECT id,title,content,source_url FROM documents WHERE is_active AND doc_type='platform_guideline'"
        ))).mappings()}
        verified_units = set()
        for item in payload['inputs']['cases']:
            source = item['candidate_source']
            doc = documents[source['document_id']]
            if (hashlib.sha256(doc['content'].encode('utf-8')).hexdigest() != source['document_sha256']
                    or doc['content'][source['start']:source['end']] != source['quote']
                    or doc['title'] != source['title'] or doc['source_url'] != source['source_url']):
                raise ValueError('冻结候选与当前数据库原文/出处不同')
            verified_units.add(source['id'])
        for item in payload['inputs']['cases']:
            tick = time.perf_counter()
            family = item['family']
            source = item['candidate_source']
            citation = KnowledgeCitation(citation_id='S1', source_type='internal',
                                         title=source['title'], excerpt=source['quote'],
                                         document_id=source['document_id'], url=source['source_url'])
            row = {'id': item['id'], 'family': family, 'status': 'executed', 'label': None,
                   'semantic_judgment_verified': False, 'method': None, 'raw_output': None}
            try:
                if family in ('query_specificity', 'version_scope'):
                    ranked = await rank_knowledge_citations(item['query'], [citation], db)
                    row['method'] = 'rank_knowledge_citations'
                    row['raw_output'] = [c.model_dump() for c in ranked]
                    row['policy_retained'] = bool(ranked)
                    if family == 'query_specificity':
                        # 只投影候选保留/过滤行为，不能称实际语义回答标签。
                        row['label'] = 'answers' if ranked else 'does_not_answer'
                        row['label_basis'] = 'source_gate_retention_proxy_not_semantic_answer'
                    else:
                        row['label'] = 'version_match' if ranked else 'version_mismatch'
                        row['label_basis'] = 'explicit_year_source_filter_proxy'
                elif family == 'statement_support':
                    report = attach_knowledge_citations({'key_findings': [item['statement'] + '[S1]']}, [citation])
                    evidence = report['knowledge_evidence']
                    if len(evidence) != 1:
                        raise ValueError('陈述核对记录数量错误')
                    row['method'] = 'attach_knowledge_citations/check_claim_evidence'
                    row['raw_output'] = evidence
                    row['label'] = 'supported' if evidence[0]['status'] == 'excerpt_matched' else 'insufficient'
                    row['label_basis'] = 'exact_text_match_or_needs_review_not_NLI'
                elif family == 'applicability':
                    row.update(status='capability_absent', method=None,
                               reason='生产代码没有患者条件与来源适用性独立判别入口；不伪造unknown预测')
                else:
                    raise ValueError('未知题型')
            except Exception as exc:
                row.update(status='execution_error', label=None, error_type=type(exc).__name__)
            row['elapsed_ms'] = round((time.perf_counter() - tick) * 1000, 3)
            rows.append(row)
        after = await settings(db)
        await db.rollback()
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        outside_after = await settings(db)
        await db.rollback()
    httpx.AsyncClient.send = original_send
    if network_attempts:
        raise ValueError('无reranker配置的基线出现意外HTTP调用，停止，不称零模型调用')
    return {'mode': 'actual_production_candidate_gate_diagnostic', 'version': payload['inputs']['version'],
            'started_at': begin, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'read_only': True, 'rolled_back': True, 'settings_before': before,
            'settings_after': outside_after, 'settings_unchanged': before == after == outside_after,
            'providers_without_credentials': configs, 'source_sha256': hashes,
            'input_sha256': payload['input_sha256'], 'rows': rows, 'extra_model_calls': len(network_attempts),
            'observed_http_attempts': len(network_attempts), 'database_source_spans_verified': len(verified_units),
            'execution_protocol': 'production_candidate_gate_v2',
            'vector_retrieval_executed': False, 'external_search_executed': False,
            'api_process_loaded': None, 'professional_review_verified': False,
            'all_52_semantic_accuracy': None}
