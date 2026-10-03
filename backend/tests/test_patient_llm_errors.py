"""患者可见模型错误契约的纯单元测试。"""

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
import pytest
from pydantic import BaseModel

from app.services.llm import LLMService
from app.services import agents as agents_module
from app.services.agents import DiagnosisAgent
from app.services.llm_errors import (
    LLMConfigurationError,
    LLMInvalidResponseError,
    patient_llm_error,
    supports_structured_output_fallback,
)


def openai_error(error_type, status_code: int):
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    if error_type is APIConnectionError:
        return APIConnectionError(request=request)
    return error_type("sensitive provider detail", response=response, body=None)


def test_timeout_has_stable_code_and_safe_patient_message():
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    error = APITimeoutError(request=request)

    actual = patient_llm_error(error)

    assert actual == {
        "code": "LLM_TIMEOUT",
        "error": "AI 服务响应超时，请保留当前内容后重试。",
    }


def test_rate_limit_does_not_expose_provider_error_details():
    actual = patient_llm_error(openai_error(RateLimitError, 429))

    assert actual["code"] == "LLM_RATE_LIMITED"
    assert "稍后重试" in actual["error"]
    assert "sensitive provider detail" not in actual["error"]


def test_provider_and_invalid_response_errors_have_distinct_codes():
    provider_error = patient_llm_error(openai_error(APIStatusError, 503))
    connection_error = patient_llm_error(openai_error(APIConnectionError, 503))
    invalid_response = patient_llm_error(json.JSONDecodeError("secret body", "{}", 0))

    assert provider_error["code"] == "LLM_PROVIDER_UNAVAILABLE"
    assert connection_error["code"] == "LLM_PROVIDER_UNAVAILABLE"
    assert invalid_response["code"] == "LLM_INVALID_RESPONSE"


def test_configuration_and_unknown_errors_are_safe_and_stable():
    config_error = patient_llm_error(LLMConfigurationError("secret API key and admin URL"))
    unrelated_value_error = patient_llm_error(ValueError("bad local value"))
    unknown_error = patient_llm_error(RuntimeError("secret response body"))

    assert config_error["code"] == "LLM_CONFIGURATION_ERROR"
    assert unrelated_value_error["code"] == "LLM_INTERNAL_ERROR"
    assert unknown_error["code"] == "LLM_INTERNAL_ERROR"
    assert "secret" not in str(config_error)
    assert "secret" not in str(unknown_error)


def test_structured_output_fallback_only_accepts_explicit_unsupported_parameter_error():
    unsupported = openai_error(APIStatusError, 400)
    unsupported.body = {"message": "response_format json_schema is not supported"}
    unavailable = openai_error(APIStatusError, 400)
    unavailable.body = {"message": "This response_format type is unavailable now"}
    timeout = APITimeoutError(request=httpx.Request("POST", "https://provider.invalid"))
    unrelated = openai_error(APIStatusError, 400)
    unrelated.body = {"message": "invalid API key"}

    assert supports_structured_output_fallback(unsupported)
    assert supports_structured_output_fallback(unavailable)
    assert not supports_structured_output_fallback(timeout)
    assert not supports_structured_output_fallback(unrelated)


class ExampleOutput(BaseModel):
    name: str


@pytest.mark.asyncio
async def test_structured_generation_does_not_retry_timeout():
    timeout = APITimeoutError(request=httpx.Request("POST", "https://provider.invalid"))
    create = AsyncMock(side_effect=timeout)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    service = LLMService()
    service._get_client = AsyncMock(return_value=client)
    service._get_default_model = AsyncMock(return_value="test-model")

    with pytest.raises(APITimeoutError):
        await service.generate_structured([{"role": "user", "content": "test"}], ExampleOutput)

    assert 1 == create.await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "response_format json_schema is not supported",
    "This response_format type is unavailable now",
])
async def test_structured_generation_falls_back_after_explicit_unsupported_schema(message):
    unsupported = openai_error(APIStatusError, 400)
    unsupported.body = {"message": message}
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"name":"ok"}'))])
    create = AsyncMock(side_effect=[unsupported, response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    service = LLMService()
    service._get_client = AsyncMock(return_value=client)
    service._get_default_model = AsyncMock(return_value="test-model")

    actual = await service.generate_structured([{"role": "user", "content": "test"}], ExampleOutput)

    assert ExampleOutput(name="ok") == actual
    assert 2 == create.await_count


def _fake_diagnosis_llm(monkeypatch, structured_error):
    @asynccontextmanager
    async def fake_session():
        yield object()

    llm = SimpleNamespace(
        chat_with_tools=AsyncMock(return_value=SimpleNamespace(content="not-json", tool_calls=None)),
        generate_structured=AsyncMock(side_effect=structured_error),
        chat=AsyncMock(return_value=SimpleNamespace(content="still not-json")),
    )
    monkeypatch.setattr(agents_module, "async_session_maker", fake_session)
    monkeypatch.setattr(agents_module, "LLMService", lambda **_kwargs: llm)
    monkeypatch.setattr(agents_module.GLOBAL_REGISTRY, "list_schemas", lambda: [])
    return llm


@pytest.mark.asyncio
async def test_diagnosis_invalid_model_output_does_not_save_fake_report(monkeypatch):
    llm = _fake_diagnosis_llm(
        monkeypatch, json.JSONDecodeError("invalid model JSON", "{}", 0)
    )
    agent = DiagnosisAgent()
    agent._update_session = AsyncMock()

    with pytest.raises(LLMInvalidResponseError) as raised:
        await agent.analyze(symptoms="合成腹泻主诉", session_id=str(uuid.uuid4()), knowledge_context="已预检的合成来源上下文")

    assert patient_llm_error(raised.value)["code"] == "LLM_INVALID_RESPONSE"
    assert llm.chat.await_count == 1
    agent._update_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_diagnosis_rate_limit_does_not_retry_plain_chat(monkeypatch):
    rate_limit = openai_error(RateLimitError, 429)
    llm = _fake_diagnosis_llm(monkeypatch, rate_limit)

    with pytest.raises(RateLimitError):
        await DiagnosisAgent().analyze(symptoms="合成腹泻主诉", knowledge_context="已预检的合成来源上下文")

    llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_onset_does_not_persist_a_chronic_symptom_label(monkeypatch):
    llm = _fake_diagnosis_llm(monkeypatch, RuntimeError("unused"))
    llm.chat_with_tools.return_value = SimpleNamespace(
        content=json.dumps({
            "primary_diagnosis": "慢性咳嗽待查（病程不详）",
            "confidence": "low",
            "key_findings": ["患者不记得起病时间。"],
        }, ensure_ascii=False),
        tool_calls=None,
    )
    agent = DiagnosisAgent()
    agent._update_session = AsyncMock()

    actual = await agent.analyze(
        symptoms="合成患者干咳，起病时间不记得",
        session_id=str(uuid.uuid4()),
        onset_unknown=True,
        knowledge_context="已预检的合成来源上下文",
    )

    assert actual.structured_output.primary_diagnosis == "咳嗽待查（病程不详）"
    assert agent._update_session.await_args.kwargs["structured"]["primary_diagnosis"] == "咳嗽待查（病程不详）"
