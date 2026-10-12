"""隔离Docker进程的四方案运行器；只读资料，原生请求计量，禁止额外网络。"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.services.query_requirements import parse_assessment, rank_assessed
from resume_variants import messages_for, system_for, request_key, VARIANTS

SOURCE_PATHS = (
    'app/services/query_requirements.py', 'app/services/llm.py', 'app/services/interview_demo.py',
    'app/services/text_privacy.py', 'app/db/session.py',
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def validate_payload(payload):
    require(set(payload) == {'protocol', 'mode', 'questions', 'input_sha256', 'source_sha256', 'expected_model_snapshot', 'tasks', 'max_http_requests'}, '执行payload字段非法或包含gold')
    require(payload['protocol'] == 'resume-four-variants-v1' and payload['mode'] in {'preflight', 'smoke', 'development'}, '执行协议或阶段非法')
    require(set(payload['source_sha256']) == set(SOURCE_PATHS), '源码白名单不同')
    questions = payload['questions']
    require(isinstance(questions, list) and len(questions) == 24 and len({q['id'] for q in questions}) == 24, '只允许开发24组')
    for q in questions:
        require(set(q) == {'id', 'query', 'candidates'}, '问题含标注字段')
        require(2 <= len(q['candidates']) <= 4, '候选数量非法')
        for s in q['candidates']:
            require(set(s) == {'id', 'document_id', 'document_sha256', 'title', 'start', 'end', 'quote', 'metadata', 'source_url'}, '来源含标注字段')
        for variant in VARIANTS:
            messages_for(q, variant)
    tasks = payload['tasks']
    require(isinstance(tasks, list) and len(tasks) == len({(t['question_id'], t['variant']) for t in tasks}), '执行任务重复')
    require(all(set(t) == {'question_id', 'variant'} and t['question_id'] in {q['id'] for q in questions} and t['variant'] in VARIANTS for t in tasks), '任务非法')
    require(type(payload['max_http_requests']) is int and payload['max_http_requests'] == len(tasks), '预算必须等于最多一次请求/任务')
    require((not tasks and payload['max_http_requests'] == 0) if payload['mode'] == 'preflight' else bool(tasks), '预检不得调用模型')
    return {q['id']: q for q in questions}


def expected_wire(question, variant, model):
    from app.services.text_privacy import redact_messages_for_provider, redact_for_provider
    messages = redact_messages_for_provider(messages_for(question, variant))
    messages.insert(0, {'role': 'system', 'content': redact_for_provider(system_for(variant))})
    return {'model': model, 'messages': messages, 'max_tokens': 4096, 'stream': False, 'thinking': {'type': 'disabled'}}


class RequestObserver:
    """校验实际发送body；不保存URL、请求头、密钥或供应商异常内容。"""
    def __init__(self, budget):
        self.budget = budget
        self.records = []
        self.active = None
        self.wire = None
        self.origin_sha256 = None

    def emit(self, event, value):
        # 发送前和收包后立即落盘；任务级解析尚未结束也能保留费用核对线索。
        print(json.dumps({event: value, 'sequence': len(self.records)}, ensure_ascii=False, allow_nan=False), flush=True)

    def before(self, request):
        require(self.active is not None and len(self.records) < self.budget, '禁止非评测网络或超预算')
        body = json.loads(request.content)
        require(body == self.wire, '实际模型/参数/消息与冻结请求不同')
        require(request.method == 'POST' and request.url.path.endswith('/chat/completions'), '禁止非chat网络请求')
        origin = [request.url.scheme, request.url.host, request.url.port]
        require(digest(json.dumps(origin).encode()) == self.origin_sha256, '实际供应商端点与预检不同')
        record = {'task': self.active, 'wire_request': body, 'request_sha256': digest(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()),
                  'status_code': None, 'native_usage': None, 'raw_content': None, 'finish_reason': None, 'response_model': None}
        self.records.append(record)
        self.emit('http_started', {k: record[k] for k in ('task', 'wire_request', 'request_sha256')})
        return record

    @staticmethod
    def after(record, response):
        record['status_code'] = response.status_code
        if response.status_code != 200:
            return
        data = response.json()
        require(isinstance(data, dict), '供应商响应不是对象')
        choices = data.get('choices')
        require(isinstance(choices, list) and len(choices) == 1, '供应商choice数量非法')
        choice = choices[0]
        record.update(raw_content=choice['message'].get('content'), finish_reason=choice.get('finish_reason'), response_model=data.get('model'))
        usage = data.get('usage')
        if isinstance(usage, dict):
            record['native_usage'] = {k: v for k, v in usage.items() if k.endswith('tokens') and type(v) is int and v >= 0}


async def settings(db):
    from sqlalchemy import text
    rows = await db.execute(text("SELECT key,value FROM system_settings WHERE key IN ('interview_demo.enabled','interview_demo.limit','interview_demo.used')"))
    return {r[0]: r[1] for r in rows}


async def validate_database(db, payload):
    from sqlalchemy import text
    hashes = {name: digest(Path(name).read_bytes()) for name in SOURCE_PATHS}
    require(hashes == payload['source_sha256'], '容器源码和本地实验起点不同')
    state = await settings(db)
    require(state.get('interview_demo.enabled', 'false') == 'false', '演示保护开启，停止而不修改配置')
    docs = {str(d['id']): dict(d) for d in (await db.execute(text("SELECT id,title,content,source_url FROM documents WHERE is_active AND doc_type='platform_guideline'"))).mappings()}
    verified = set()
    for q in payload['questions']:
        for source in q['candidates']:
            doc = docs.get(source['document_id'])
            require(doc is not None and digest(doc['content'].encode()) == source['document_sha256'], '当前文档指纹不同')
            require(doc['content'][source['start']:source['end']] == source['quote'] and doc['title'] == source['title'] and doc['source_url'] == source['source_url'], '当前资料摘录/出处不同')
            verified.add(source['id'])
    return state, hashes, len(verified)


async def run(payload):
    questions = validate_payload(payload)
    from openai import DefaultAsyncHttpxClient
    from sqlalchemy import text
    from app.db.session import async_engine, async_session_maker
    from app.services.llm import LLMService
    import httpx
    async_engine.echo = False
    logging.disable(logging.CRITICAL)
    started = datetime.now(timezone.utc).isoformat()
    observer = RequestObserver(payload['max_http_requests'])
    original_send = DefaultAsyncHttpxClient.send
    forbidden_attempts = []
    async def forbidden(*args, **kwargs):
        forbidden_attempts.append(1)
        raise ValueError('禁止额外HTTP')
    async def observed_send(client, request, *args, **kwargs):
        record = observer.before(request)
        response = await original_send(client, request, *args, **kwargs)
        observer.after(record, response)
        observer.emit('http_finished', record)
        return response
    rows = []
    # SDK2底层可能独立于httpx；同时阻断非SDK的httpx入口，计量真实SDK客户端send。
    with patch.object(httpx.AsyncClient, 'send', forbidden), patch.object(DefaultAsyncHttpxClient, 'send', observed_send):
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            before, hashes, verified = await validate_database(db, payload)
            service = LLMService(db=db, platform='web', model_type='diagnosis', timeout=60, max_retries=0)
            client = await service._get_client()
            try:
                model = await service._get_default_model()
                require(bool(model) and client.max_retries == 0, '模型为空或SDK会重试')
                # 防止底层自动跟随重定向而绕过一次send的请求预算。
                client._client.follow_redirects = False
                origin = [client.base_url.scheme, client.base_url.host, client.base_url.port]
                observer.origin_sha256 = digest(json.dumps(origin).encode())
                snapshot = {'provider': service.provider, 'model': model, 'sdk_retries': client.max_retries,
                            'temperature_wire': 'omitted', 'max_tokens': 4096, 'timeout_seconds': 60,
                            'thinking': 'disabled', 'follow_redirects': False,
                            'endpoint_sha256': digest(str(client.base_url).encode()), 'origin_sha256': observer.origin_sha256}
                if payload['mode'] != 'preflight':
                    require(snapshot == payload['expected_model_snapshot'], '模型配置与预检不同')
                async def reuse_client():
                    return client
                service._get_client = reuse_client
                for task in payload['tasks']:
                    q, variant = questions[task['question_id']], task['variant']
                    observer.active = dict(task)
                    observer.wire = expected_wire(q, variant, model)
                    count = len(observer.records)
                    tick = time.perf_counter()
                    result = {'question_id': q['id'], 'variant': variant, 'request_key': request_key(q, variant, snapshot),
                              'raw_output': None, 'parsed': None, 'ranked_ids': None, 'status': 'error', 'error_type': None,
                              'native_usage': None, 'http_attempts': 0}
                    try:
                        response = await asyncio.wait_for(service.chat(messages=messages_for(q, variant), system_prompt=system_for(variant), temperature=0, max_tokens=4096), timeout=60)
                        require(len(observer.records) == count + 1, 'HTTP次数不同')
                        record = observer.records[-1]
                        result.update(raw_output=response.content, native_usage=record['native_usage'])
                        require(record['status_code'] == 200 and record['finish_reason'] == response.finish_reason == 'stop', '模型输出未完整结束')
                        require(record['raw_content'] == response.content and record['response_model'] == response.model, '原生响应与服务返回不同')
                        require(record['native_usage'] is not None and {'prompt_tokens', 'completion_tokens'} <= set(record['native_usage']), '原生usage缺失，不把服务默认0当真实计量')
                        parsed = parse_assessment(response.content, [{'id': s['id'], 'excerpt': s['quote']} for s in q['candidates']])
                        result.update(parsed=parsed, ranked_ids=rank_assessed(parsed), status='success')
                        require(not any(c['label'] == 'unknown' for c in parsed['candidates']), '出现unknown，停止扩量')
                    except Exception as exc:
                        result.update(status='error', error_type=type(exc).__name__)
                    finally:
                        result.update(elapsed_ms=round((time.perf_counter() - tick) * 1000, 3), http_attempts=len(observer.records) - count)
                        observer.active = None
                    rows.append(result)
                    # 每题立即输出可恢复证据，父进程逐行保存；进程中断不得自动补发未知请求。
                    print(json.dumps({'checkpoint': result, 'requests': observer.records[count:]}, ensure_ascii=False, allow_nan=False), flush=True)
                    if result['status'] != 'success':
                        break
                after = await settings(db)
                await db.rollback()
            finally:
                await client.close()
        async with async_session_maker() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            outside = await settings(db)
            await db.rollback()
    require(before == after == outside and not forbidden_attempts, '只读/配置/网络门禁变化')
    return {'protocol': payload['protocol'], 'mode': payload['mode'], 'input_sha256': payload['input_sha256'],
            'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'model_snapshot': snapshot, 'source_sha256': hashes, 'verified_sources': verified,
            'settings_before': before, 'settings_after': outside, 'settings_unchanged': True,
            'read_only': True, 'rolled_back': True, 'read_gold': False, 'vector_retrieval_executed': False,
            'external_search_executed': False, 'requests': observer.records, 'rows': rows,
            'requested_tasks': len(payload['tasks']), 'complete': len(rows) == len(payload['tasks']) and all(r['status'] == 'success' for r in rows),
            'forbidden_network_attempts': len(forbidden_attempts), 'money_cost': None}
