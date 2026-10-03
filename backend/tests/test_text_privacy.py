"""统一出站遮蔽不能改变本地病情文本与协议字段。"""
from app.services.text_privacy import redact_text, redact_for_provider, redact_messages_for_provider

import json
from unittest.mock import AsyncMock
import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel
from app.services.llm import LLMService


def test_outbound_text_hides_explicit_identifiers_and_preserves_clinical_values():
    text = "姓名：陈小禾，电话：13800000000；住址：合成市示例路99号；发热3天，体温39℃，CRP 80mg/L。"
    result = redact_text(text)
    assert "陈小禾" not in result.text and "13800000000" not in result.text
    assert "合成市示例路99号" not in result.text
    assert all(s in result.text for s in ["3天", "39℃", "80mg/L"])
    assert len(text) == len(result.text)
    assert all(text[s.start:s.end] == s.text for s in result.spans)
    messages = [{"role": "user", "content": text}]
    sent = redact_for_provider(messages)
    assert text == messages[0]["content"]
    assert result.text == sent[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "stream", "tools", "structured", "fallback", "vision"])
async def test_actual_openai_transport_receives_redacted_text_in_all_chat_modes(monkeypatch, mode):
    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if mode == "fallback" and len(requests) == 1:
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported", "type": "invalid_request_error"}})
        if body.get("stream"):
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=(
                'data: {"id":"synthetic","object":"chat.completion.chunk","created":1,"model":"synthetic","choices":[{"index":0,"delta":{"content":"合成回复"},"finish_reason":null}]}\n\ndata: [DONE]\n\n').encode())
        return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 1,
            "model": "synthetic", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": '{"answer":"合成回复"}'}, "finish_reason": "stop"}]})
    client = AsyncOpenAI(api_key="synthetic-test-only", base_url="https://synthetic.invalid/v1",
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    service = LLMService(provider="synthetic")
    monkeypatch.setattr(service, "_get_client", AsyncMock(return_value=client))
    monkeypatch.setattr(service, "_get_default_model", AsyncMock(return_value="synthetic"))
    text = "姓名：陈小禾，电话：13800000000；咳嗽3天，体温39℃"
    messages = [{"role": "system", "content": "合成规则"}, {"role": "user", "content": text}]
    class Output(BaseModel):
        answer: str
    try:
        if mode == "chat":
            await service.chat(messages)
        elif mode == "stream":
            assert ["合成回复"] == [s async for s in service.chat_stream(messages)]
        elif mode == "tools":
            messages.extend([
                {"role": "assistant", "tool_calls": [{"id": "13800000000", "type": "function",
                    "function": {"name": "synthetic_tool", "arguments": '{"phone":"13900000000"}'}}]},
                {"role": "tool", "tool_call_id": "13800000000", "content": '姓名：李晓雨，咳嗽3天'}])
            await service.chat_with_tools(messages, tools=[{"type": "function", "function": {
                "name": "synthetic_tool", "description": "合成工具，姓名：李晓雨，电话：13900000000",
                "parameters": {"type": "object", "properties": {"phone": {"type": "string"}}}}}])
        elif mode in {"structured", "fallback"}:
            await service.generate_structured(messages, Output)
        else:
            await service.chat_vision(text, b"synthetic-image-bytes")
    finally:
        await client.close()
    sent = json.dumps(requests[0], ensure_ascii=False)
    assert "陈小禾" not in sent
    assert "3天" in sent and "39℃" in sent
    assert text == messages[1]["content"] and "合成规则" == messages[0]["content"]
    assert all("陈小禾" not in json.dumps(body, ensure_ascii=False) for body in requests)
    if mode == "tools":
        assert "13800000000" not in requests[0]["messages"][1]["content"]
        assert "13800000000" == requests[0]["messages"][2]["tool_calls"][0]["id"] == requests[0]["messages"][3]["tool_call_id"]
        assert "李晓雨" not in sent and "13900000000" not in sent
        assert "synthetic_tool" == requests[0]["tools"][0]["function"]["name"]
        assert {"phone": {"type": "string"}} == requests[0]["tools"][0]["function"]["parameters"]["properties"]
    else:
        assert all("13800000000" not in json.dumps(body) for body in requests)
    if mode == "fallback":
        assert len(requests) == 2


def test_json_tool_messages_and_image_data_keep_protocol_and_original_unchanged():
    tree = [{"role": "tool", "tool_call_id": "call-1", "content": json.dumps({
        "patient_name": "李晓雨", "finding": "目前咳嗽3天", "phone": "13900000000"}, ensure_ascii=True)},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,13800000000"}},
                                       {"type": "text", "text": "姓名：周安，发热2天"}]}]
    sent = redact_for_provider(tree)
    assert "call-1" == sent[0]["tool_call_id"]
    payload = json.loads(sent[0]["content"])
    assert "***" == payload["patient_name"] and "目前咳嗽3天" == payload["finding"]
    assert "13900000000" not in payload["phone"]
    assert tree[1]["content"][0] == sent[1]["content"][0]
    assert "周安" not in sent[1]["content"][1]["text"]
    assert "李晓雨" == json.loads(tree[0]["content"])["patient_name"]


def test_numeric_tool_call_identity_survives_but_parameters_are_masked():
    tree = [{"role": "assistant", "tool_calls": [{"id": "13800000000", "type": "function",
        "function": {"name": "synthetic_tool", "arguments": '{"phone":"13900000000"}'}}]},
        {"role": "tool", "tool_call_id": "13800000000", "content": '电话：13900000000'}]
    sent = redact_messages_for_provider(tree)
    assert "13800000000" == sent[0]["tool_calls"][0]["id"] == sent[1]["tool_call_id"]
    assert "13900000000" not in sent[0]["tool_calls"][0]["function"]["arguments"]
    assert "13900000000" not in sent[1]["content"]


def test_frozen_privacy_cases_keep_all_annotated_values_without_false_redaction():
    from pathlib import Path
    catalog = json.loads((Path(__file__).resolve().parents[2] / "evals/openmed-transfer/catalog.json").read_text(encoding="utf-8"))
    for case in catalog["cases"]:
        text = case["input"]["text"]
        masked = redact_text(text).text
        gold = case["gold"]
        allowed = {i for span in gold["pii"] for i in range(span["start"], span["end"])}
        changed = {i for i, (old, new) in enumerate(zip(text, masked)) if old != new}
        assert changed <= allowed, case["id"]
        for span in gold["protected"]:
            assert span["text"] == masked[span["start"]:span["end"]], case["id"]
        for span in gold["pii"]:
            assert "*" * len(span["text"]) == masked[span["start"]:span["end"]], case["id"]


@pytest.mark.asyncio
async def test_embedding_batch_is_redacted_before_actual_transport(monkeypatch):
    from app.services.embedding import EmbeddingService
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"object": "list", "model": "synthetic", "data": [
            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 1, "total_tokens": 1}})
    client = AsyncOpenAI(api_key="synthetic-test-only", base_url="https://synthetic.invalid/v1",
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    service = EmbeddingService(None)
    service._model = "synthetic"
    monkeypatch.setattr(service, "_get_client", AsyncMock(return_value=client))
    texts = ["姓名：陈小禾，咳嗽3天，电话：13800000000"]
    try:
        assert [[0.1, 0.2]] == await service.embed(texts)
    finally:
        await client.close()
    assert "陈小禾" not in captured[0]["input"][0]
    assert "13800000000" not in captured[0]["input"][0] and "3天" in captured[0]["input"][0]
    assert "陈小禾" in texts[0]


@pytest.mark.asyncio
async def test_search_public_entry_and_logs_do_not_expose_identifiers(monkeypatch, caplog):
    from app.services import external_search
    agent = external_search.ExternalSearchAgent(base_url="https://synthetic.invalid")
    captured = []
    original_client = httpx.AsyncClient
    def handle(request):
        captured.append(str(request.url))
        return httpx.Response(200, json={"results": []})
    monkeypatch.setattr(external_search.httpx, "AsyncClient", lambda **kwargs:
                        original_client(transport=httpx.MockTransport(handle), **kwargs))
    assert [] == await agent.search_guidelines("姓名：陈小禾，电话：13800000000；咳嗽3天")
    from urllib.parse import unquote
    sent = unquote(captured[0])
    assert "陈小禾" not in sent and "13800000000" not in sent and "3天" in sent
    assert "陈小禾" not in caplog.text and "13800000000" not in caplog.text
