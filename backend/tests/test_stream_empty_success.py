"""路由流空输出回归：没有有效内容不能宣称响应完成。"""
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request


async def route_events(monkeypatch, chunks, failure=None):
    from app.api.v1 import agents as api

    @asynccontextmanager
    async def fake_db():
        yield Mock()

    async def text_stream(**kwargs):
        for chunk in chunks:
            yield chunk
        if failure is not None:
            raise failure

    master = SimpleNamespace(master=SimpleNamespace(
        classify_intent=AsyncMock(return_value={'intent': 'general'})
    ))
    monkeypatch.setattr(api, 'AgentOrchestrator', Mock(return_value=master))
    monkeypatch.setattr(api, 'async_session_maker', fake_db)
    monkeypatch.setattr(api, 'LLMService', Mock(return_value=SimpleNamespace(chat_stream=text_stream)))
    request = Request({'type':'http','query_string':b'','headers':[]})
    ctx = SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4()), is_guest=False, platform='web')
    response = await api.route_stream(
        req=api.RouteStreamRequest(message='请介绍你能提供的帮助'),
        request=request, ctx=ctx, db=AsyncMock(scalar=AsyncMock(return_value=None)),
    )
    return ''.join([chunk async for chunk in response.body_iterator])


@pytest.mark.asyncio
@pytest.mark.parametrize('chunks', [[], ['', ' \n\t']])
async def test_route_empty_text_cannot_complete(monkeypatch, chunks):
    events = await route_events(monkeypatch, chunks)
    assert 'event: complete' not in events
    assert 'event: error' in events
    assert 'LLM_EMPTY_RESPONSE' in events


@pytest.mark.asyncio
async def test_route_valid_text_preserves_chunks_and_completes(monkeypatch):
    chunks = ['', ' \n', '有效回复', '。']
    events = await route_events(monkeypatch, chunks)
    text_events = [json.loads(item.split('data: ', 1)[1])['text']
                   for item in events.split('\n\n') if item.startswith('event: text')]
    assert chunks == text_events
    assert 'event: error' not in events
    assert 'event: complete' in events


@pytest.mark.asyncio
@pytest.mark.parametrize('chunks', [[], ['部分回复']])
async def test_route_provider_failure_never_completes_or_leaks_details(monkeypatch, chunks):
    events = await route_events(monkeypatch, chunks, RuntimeError('synthetic-provider-secret'))
    assert 'event: error' in events
    assert 'event: complete' not in events
    assert 'synthetic-provider-secret' not in events
