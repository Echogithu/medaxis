"""验证演示控制；供应商使用内存传输，不连接业务数据库或真实模型。"""
import asyncio
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from openai import APIConnectionError, AsyncOpenAI

from app.services import interview_demo as demo
from app.models.user import UserRole

USER = 'd59b206e-81d2-448a-bbfd-57dd095fa276'


class Session:
    def __init__(self, counter, lock):
        self.counter, self.lock, self.locked = counter, lock, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if self.locked:
            self.lock.release()

    async def scalar(self, statement):
        await self.lock.acquire()
        self.locked = True
        return self.counter

    async def commit(self):
        pass


def quota(monkeypatch, limit=20, enabled=True):
    counter, lock = SimpleNamespace(value='0'), asyncio.Lock()
    monkeypatch.setattr(demo, 'AsyncSessionLocal', lambda: Session(counter, lock))
    monkeypatch.setattr(demo, 'load_policy', AsyncMock(return_value=demo.DemoPolicy(enabled, USER, limit, 0)))
    return counter


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_exceed_total(monkeypatch):
    counter = quota(monkeypatch)
    sent = []
    def provider(request):
        sent.append(request)
        return httpx.Response(200, json={'ok': True})
    actor = demo.demo_actor.set(USER)
    try:
        async with demo.provider_http_client(transport=httpx.MockTransport(provider)) as client:
            replies = await asyncio.gather(*(client.get('https://provider.test/ai') for _ in range(40)), return_exceptions=True)
    finally:
        demo.demo_actor.reset(actor)
    assert 20 == len(sent)
    assert '20' == counter.value
    assert 20 == sum(isinstance(reply, HTTPException) and reply.status_code == 429 for reply in replies)


@pytest.mark.asyncio
async def test_sdk_retry_is_charged_and_exhaustion_never_sends(monkeypatch):
    counter = quota(monkeypatch, limit=2)
    sent = []
    def provider(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(500, json={'error': {'message': 'temporary'}})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
            'model': 'test', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '真实协议测试'}, 'finish_reason': 'stop'}]})
    actor = demo.demo_actor.set(USER)
    try:
        async with AsyncOpenAI(api_key='test-only', base_url='https://provider.test/v1', max_retries=1,
            http_client=demo.provider_http_client(transport=httpx.MockTransport(provider))) as client:
            result = await client.chat.completions.create(model='test', messages=[{'role': 'user', 'content': 'hi'}])
            assert '真实协议测试' == result.choices[0].message.content
            with pytest.raises(APIConnectionError):
                await client.chat.completions.create(model='test', messages=[{'role': 'user', 'content': 'again'}])
    finally:
        demo.demo_actor.reset(actor)
    assert 2 == len(sent)
    assert '2' == counter.value


@pytest.mark.asyncio
async def test_background_and_other_identity_do_not_send(monkeypatch):
    counter = quota(monkeypatch)
    for actor_value in (None, str(UUID(int=1))):
        actor = demo.demo_actor.set(actor_value)
        try:
            with pytest.raises(HTTPException) as error:
                await demo.reserve_provider_request(httpx.Request('POST', 'https://provider.test/ai'))
            assert 403 == error.value.status_code
        finally:
            demo.demo_actor.reset(actor)
    assert '0' == counter.value


@pytest.mark.asyncio
async def test_disabled_policy_keeps_provider_available(monkeypatch):
    counter = quota(monkeypatch, enabled=False)
    async with demo.provider_http_client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        assert 200 == (await client.get('https://provider.test/ai')).status_code
    assert '0' == counter.value


@pytest.mark.asyncio
@pytest.mark.parametrize('values', [
    {'enabled': 'true'},
    {'enabled': 'true', 'user_id': USER, 'limit': '21', 'used': '0'},
    {'enabled': 'true', 'user_id': USER, 'limit': '20', 'used': '-1'},
    {'enabled': 'unexpected'},
])
async def test_invalid_policy_fails_closed(values):
    rows = [SimpleNamespace(key=demo.PREFIX + key, value=value) for key, value in values.items()]
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)))
    with pytest.raises(HTTPException) as error:
        await demo.load_policy(db)
    assert 503 == error.value.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/api/v1/auth/guest', '/api/v1/auth/guest/migrate', '/api/v1/auth/register', '/api/v1/auth/register/doctor', '/api/v1/auth/switch-role', '/api/v1/auth/change-password', '/api/v1/llm/chat'])
async def test_unwanted_entry_points_are_denied(monkeypatch, path):
    quota(monkeypatch)
    app = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo.InterviewDemoMiddleware(app)), base_url='http://test') as client:
        assert 403 == (await client.post(path)).status_code
    app.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('identity,status', [(None, 401), (str(UUID(int=2)), 403), (USER, 200)])
@pytest.mark.parametrize('auth_kind', ['header', 'query', 'cookie'])
async def test_identity_and_sse_token_transport(monkeypatch, identity, status, auth_kind):
    quota(monkeypatch)
    from app.api import deps
    async def resolve(token, db):
        assert 'test-token' == token
        user = SimpleNamespace(id=UUID(identity), role=UserRole.PATIENT) if identity else None
        return user, 'web', False, None
    monkeypatch.setattr(deps, '_resolve_token', resolve)
    async def app(scope, receive, send):
        assert USER == demo.demo_actor.get()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'event: complete\n\n'})
    headers = {'Authorization': 'Bearer test-token'} if auth_kind == 'header' else {'Cookie': 'auth_token=test-token'} if auth_kind == 'cookie' else {}
    suffix = '?token=test-token' if auth_kind == 'query' else ''
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo.InterviewDemoMiddleware(app)), base_url='http://test') as client:
        assert status == (await client.get('/api/v1/agent/stream' + suffix, headers=headers)).status_code
    assert demo.demo_actor.get() is None


@pytest.mark.asyncio
async def test_disabled_mode_preserves_downstream_errors(monkeypatch):
    quota(monkeypatch, enabled=False)
    async def app(scope, receive, send):
        raise RuntimeError('原应用错误')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo.InterviewDemoMiddleware(app)), base_url='http://test') as client:
        with pytest.raises(RuntimeError, match='原应用错误'):
            await client.get('/api/v1/existing')


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/api/v1/patient/reports', f'/api/v1/patient/cases/{USER}/reports'])
async def test_uninitialized_report_routes_do_not_reach_database(monkeypatch, path):
    quota(monkeypatch)
    from app.api import deps
    monkeypatch.setattr(deps, '_resolve_token', AsyncMock(return_value=(SimpleNamespace(id=UUID(USER), role=UserRole.PATIENT), 'web', False, None)))
    app = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo.InterviewDemoMiddleware(app)), base_url='http://test') as client:
        reply = await client.get(path, headers={'Authorization': 'Bearer test-token'})
        assert 503 == reply.status_code
        assert '病例附件' in reply.json()['detail']
    app.assert_not_called()


@pytest.mark.asyncio
async def test_demo_errors_do_not_expose_debug_details(monkeypatch):
    quota(monkeypatch)
    from app.api import deps
    monkeypatch.setattr(deps, '_resolve_token', AsyncMock(return_value=(SimpleNamespace(id=UUID(USER), role=UserRole.PATIENT), 'web', False, None)))
    async def app(scope, receive, send):
        raise RuntimeError('不得返回的内部细节')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo.InterviewDemoMiddleware(app)), base_url='http://test') as client:
        reply = await client.get('/api/v1/existing', headers={'Authorization': 'Bearer test-token'})
        assert 500 == reply.status_code
        assert '不得返回' not in reply.text
    assert demo.demo_actor.get() is None


@pytest.mark.asyncio
async def test_stream_error_resets_actor_without_second_response(monkeypatch):
    quota(monkeypatch)
    from app.api import deps
    monkeypatch.setattr(deps, '_resolve_token', AsyncMock(return_value=(SimpleNamespace(id=UUID(USER), role=UserRole.PATIENT), 'web', False, None)))
    messages = []
    async def send(message):
        messages.append(message)
    async def app(scope, receive, send):
        assert USER == demo.demo_actor.get()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        raise RuntimeError('流式请求中断')
    with pytest.raises(RuntimeError, match='流式请求中断'):
        await demo.InterviewDemoMiddleware(app)({'type': 'http', 'path': '/api/v1/existing',
            'headers': [(b'authorization', b'Bearer test-token')]}, AsyncMock(), send)
    assert 1 == len(messages)
    assert demo.demo_actor.get() is None


@pytest.mark.asyncio
async def test_storage_failure_never_sends_provider_request(monkeypatch):
    quota(monkeypatch)
    monkeypatch.setattr(demo, 'load_policy', AsyncMock(side_effect=RuntimeError('database unavailable')))
    sent = []
    async with demo.provider_http_client(transport=httpx.MockTransport(lambda request: sent.append(request))) as client:
        with pytest.raises(RuntimeError, match='database unavailable'):
            await client.get('https://provider.test/ai')
    assert [] == sent
