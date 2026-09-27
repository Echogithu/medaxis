"""Routing and first-turn regressions; no live model or patient database required."""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models.config import LLMProviderConfig
from app.models.interview import InterviewState
from app.services import agents, intent
from app.services import llm as llm_module
from app.services.llm import LLMResponse
from app.services.orchestrator import InterviewGenerationError, InterviewOrchestrator, Track1Agent


def response(data, *, finish="stop"):
    return LLMResponse(
        content=json.dumps(data, ensure_ascii=False), model="test", provider="test",
        usage_prompt_tokens=100, usage_completion_tokens=80, finish_reason=finish,
    )


def questions():
    return {
        "basic_module": [
            {"question_id": "hpi_onset", "question": "您从什么时候开始不舒服？",
             "type": "choice", "options": ["今天", "昨天", "更早"], "phase": "hpi_onset"},
            {"question_id": "hpi_associated", "question": "您目前还有哪些不适？",
             "type": "multi_choice", "options": ["恶心", "乏力", "以上都没有"], "phase": "hpi_associated"},
        ],
        "red_flags": [],
    }


def config(**kwargs):
    return SimpleNamespace(
        provider=kwargs.get("provider", "typesafe"), platform=kwargs.get("platform"),
        default_model="jev-latest", base_url="https://api.typesafe.ai/v1",
        api_key_encrypted="encrypted-test-value",
    )


@asynccontextmanager
async def fake_db():
    yield Mock()


@pytest.mark.asyncio
async def test_jev_uses_decision_protocol_and_bounded_context(monkeypatch):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={
            "model": "jev-test-version",
            "answers": {"intent": {"type": "choice", "choice": "diagnosis", "confidence": .9}},
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr(intent.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(intent, "decrypt_value", lambda value: "test-key")
    state = intent.classification_state("头疼还发烧", {
        "has_completed_diagnosis": True, "diagnosis_summary": "摘要" * 400,
        "user_id": "private-id", "interview_collected": {"__internal__": "omit", "hpi_onset": "昨天"},
    })
    result = await intent.classify_with_jev(config(), state)
    assert result["intent"] == "diagnosis"
    assert result["classifier_model"] == "jev-test-version"
    assert result["confidence_score"] == .9
    request = captured[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    body = json.loads(request.content)
    assert body["questions"]["intent"]["type"] == "choice"
    assert "other" in body["questions"]["intent"]["criteria"]
    assert body["state"]["has_completed_diagnosis"] is True
    assert len(body["state"]["diagnosis_summary"]) == 300
    assert "private-id" not in request.content.decode()
    assert "__internal__" not in request.content.decode()


@pytest.mark.parametrize("choice,confidence", [("general", .2), ("other", .99)])
@pytest.mark.asyncio
async def test_jev_uncertainty_does_not_route_to_general_answers(monkeypatch, choice, confidence):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "answers": {"intent": {"type": "choice", "choice": choice, "confidence": confidence}},
    }))
    monkeypatch.setattr(intent.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(intent, "decrypt_value", lambda value: "test-key")
    result = await intent.classify_with_jev(config(), {"message": "不明确的请求"})
    assert (result["intent"], result["confidence"]) == ("diagnosis", "low")


@pytest.mark.parametrize("answer", [
    {"type": "choice", "choice": "invented", "confidence": .9},
    {"type": "choice", "choice": "general", "confidence": True},
    {"type": "choice", "choice": "general", "confidence": 1.1},
    {"type": "choice", "choice": "general"},
])
@pytest.mark.asyncio
async def test_invalid_jev_responses_are_rejected(monkeypatch, answer):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"answers": {"intent": answer}}))
    monkeypatch.setattr(intent.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(intent, "decrypt_value", lambda value: "test-key")
    with pytest.raises(ValueError):
        await intent.classify_with_jev(config(), {"message": "test"})


@pytest.mark.asyncio
async def test_classifier_selection_is_role_and_platform_scoped():
    engine = create_engine("sqlite://")
    LLMProviderConfig.__table__.create(engine)
    with Session(engine) as db:
        for provider, platform, role, active, default in [
            ("diagnosis-default", None, "diagnosis", True, True),
            ("global-fallback", None, "classify", True, False),
            ("global-default", None, "classify", True, True),
            ("web-only", "web", "classify", True, False),
            ("disabled", "web", "classify", False, True),
            ("ios-only", "ios", "classify", True, True),
        ]:
            db.add(LLMProviderConfig(
                provider=provider, platform=platform, name=provider, model_type=role,
                is_active=active, is_default=default, base_url="https://example.test/v1",
                default_model="test", api_key_encrypted="test",
            ))
        db.commit()
        adapter = SimpleNamespace(execute=AsyncMock(side_effect=db.execute))
        assert (await intent.get_classifier_config(adapter, "web")).provider == "web-only"
        assert (await intent.get_classifier_config(adapter, "android")).provider == "global-default"
        assert (await intent.get_classifier_config(adapter)).provider == "global-default"
    engine.dispose()


@pytest.mark.asyncio
async def test_llm_factory_preserves_classification_role_and_credentials(monkeypatch):
    engine = create_engine("sqlite://")
    LLMProviderConfig.__table__.create(engine)
    monkeypatch.setattr(llm_module, "decrypt_value", lambda value: value)
    with Session(engine) as db:
        for role, model in [("diagnosis", "slow-model"), ("classify", "fast-model")]:
            db.add(LLMProviderConfig(
                provider="shared-provider", name=role, model_type=role,
                base_url=f"https://{role}.example.test/v1", default_model=model,
                api_key_encrypted=f"{role}-key", is_default=True,
            ))
        db.commit()
        adapter = SimpleNamespace(execute=AsyncMock(side_effect=db.execute))
        service = await llm_module.get_llm_service(adapter, model_type="classify")
        assert await service._get_default_model() == "fast-model"
        factory = Mock()
        monkeypatch.setattr(llm_module, "AsyncOpenAI", factory)
        await service._get_client()
        assert factory.call_args.kwargs["api_key"] == "classify-key"
        assert factory.call_args.kwargs["base_url"] == "https://classify.example.test/v1"
        with pytest.raises(ValueError, match="classification config"):
            await llm_module._get_provider_config(adapter, "missing", model_type="classify")
    engine.dispose()


@pytest.mark.asyncio
async def test_master_prefers_jev_over_selected_diagnostic_provider(monkeypatch):
    monkeypatch.setattr(agents, "async_session_maker", fake_db)
    selector = AsyncMock(return_value=config())
    monkeypatch.setattr(agents, "get_classifier_config", selector)
    jev = AsyncMock(return_value={"intent": "research", "confidence": "high"})
    monkeypatch.setattr(agents, "classify_with_jev", jev)
    llm = Mock()
    monkeypatch.setattr(agents, "LLMService", llm)
    result = await agents.MasterAgent(provider="slow-diagnosis", platform="web").classify_intent("最新指南")
    assert result["intent"] == "research"
    assert selector.await_args.args[1] == "web"
    llm.assert_not_called()


@pytest.mark.parametrize("dedicated", [True, False])
@pytest.mark.asyncio
async def test_chat_classifier_has_compact_output_and_no_automatic_retries(monkeypatch, dedicated):
    monkeypatch.setattr(agents, "async_session_maker", fake_db)
    monkeypatch.setattr(agents, "get_classifier_config", AsyncMock(return_value=config(provider="fast-chat") if dedicated else None))
    llm = SimpleNamespace(chat=AsyncMock(return_value=response({"intent": "planning", "confidence": "high"})))
    factory = Mock(return_value=llm)
    monkeypatch.setattr(agents, "LLMService", factory)
    result = await agents.MasterAgent(provider="diagnosis").classify_intent("安排复诊")
    assert result["intent"] == "planning"
    assert llm.chat.await_args.kwargs["max_tokens"] == 96
    assert factory.call_args.kwargs["model_type"] == ("classify" if dedicated else "diagnosis")
    assert factory.call_args.kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_classification_deadline_cancels_request_without_second_model_call(monkeypatch):
    monkeypatch.setattr(agents, "async_session_maker", fake_db)
    monkeypatch.setattr(agents, "get_classifier_config", AsyncMock(return_value=config()))
    cancelled = asyncio.Event()

    async def blocked(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(agents, "classify_with_jev", blocked)
    monkeypatch.setattr(agents, "INTENT_TIMEOUT_SECONDS", .01)
    llm = Mock()
    monkeypatch.setattr(agents, "LLMService", llm)
    result = await agents.MasterAgent().classify_intent("头疼还发烧")
    assert result["confidence"] == "low"
    assert result["intent"] == "diagnosis"
    assert cancelled.is_set()
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_first_interview_is_compact_and_preserves_safety_fields():
    data = questions()
    data["red_flags"] = ["用户明确报告的危险信号"]
    llm = SimpleNamespace(chat=AsyncMock(return_value=response(data)))
    cards, diffs, flags, reasoning = await Track1Agent(llm).generate(InterviewState(chief_complaint="头疼还发烧"))
    assert len(cards) == 2 and all(len(card.options) >= 2 for card in cards)
    assert flags == data["red_flags"]
    assert diffs == [] and reasoning == ""
    assert llm.chat.await_count == 1
    assert llm.chat.await_args.kwargs["max_tokens"] == 768
    prompt = llm.chat.await_args.kwargs["messages"][0]["content"]
    assert "red_flags" in prompt
    assert '"differential_diagnoses"' not in prompt


@pytest.mark.parametrize("state", [
    InterviewState(asked_questions=["hpi_onset"]),
    InterviewState(lab_reports=[{"summary": "existing report"}]),
    InterviewState(collected_info={"hpi_onset": "昨天"}),
])
@pytest.mark.asyncio
async def test_followup_and_reports_keep_full_generation(state):
    data = questions()
    data["differential_diagnoses"] = [{"diagnosis": "test hypothesis", "confidence": "low"}]
    llm = SimpleNamespace(chat=AsyncMock(return_value=response(data)))
    _, diffs, _, _ = await Track1Agent(llm).generate(state)
    assert llm.chat.await_args.kwargs["max_tokens"] == 2048
    assert len(diffs) == 1


@pytest.mark.asyncio
async def test_compact_truncation_recovers_once_with_full_budget():
    llm = SimpleNamespace(chat=AsyncMock(side_effect=[response({}, finish="length"), response(questions())]))
    cards, *_ = await Track1Agent(llm).generate(InterviewState())
    assert len(cards) == 2
    assert [call.kwargs["max_tokens"] for call in llm.chat.await_args_list] == [768, 2048]


@pytest.mark.asyncio
async def test_failed_first_generation_cannot_become_a_completed_diagnosis():
    llm = SimpleNamespace(chat=AsyncMock(return_value=response({})))
    search = AsyncMock()
    state = InterviewState(chief_complaint="头疼还发烧")
    with pytest.raises(InterviewGenerationError):
        await InterviewOrchestrator(llm, search).decide_next(state)
    assert state.phase == "interviewing" and not state.is_sufficient
    search.assert_not_awaited()
    assert llm.chat.await_count == 2


@pytest.mark.parametrize("failure", [
    InterviewGenerationError("首轮问诊问题生成失败，请重试。"),
    RuntimeError("synthetic provider failure"),
])
@pytest.mark.asyncio
async def test_stream_reports_generation_failure_instead_of_direct_diagnosis(monkeypatch, failure):
    from app.api.v1 import agents as api

    master = SimpleNamespace(
        master=SimpleNamespace(classify_intent=AsyncMock(return_value={"intent": "diagnosis"})),
        _create_session=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
    )
    diagnostic = SimpleNamespace(
        interview=AsyncMock(side_effect=failure),
        run_full_diagnosis_workflow=AsyncMock(),
    )
    monkeypatch.setattr(api, "AgentOrchestrator", Mock(return_value=master))
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "async_session_maker", fake_db)
    request = Request({"type": "http", "query_string": b"", "headers": [(b"authorization", b"Bearer test")]})
    ctx = SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4()), is_guest=False, platform="web")
    stream = await api.route_stream(message="头疼还发烧", request=request, ctx=ctx, db=AsyncMock())
    events = "".join([chunk async for chunk in stream.body_iterator])
    assert "event: error" in events
    assert "event: structured" not in events
    diagnostic.run_full_diagnosis_workflow.assert_not_awaited()
    assert api.DiagnosisAgent.call_args.kwargs["platform"] == "web"


@pytest.mark.asyncio
async def test_stream_saves_case_before_report_and_returns_case_id(monkeypatch):
    from app.api.v1 import agents as api
    from app.db import redis_client

    session_id = uuid.uuid4()
    case_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    report = {
        "primary_diagnosis": "合成演示报告",
        "confidence": "low",
        "severity": "unknown",
        "red_flags": [],
    }
    state = SimpleNamespace(red_flags_detected=[], is_sufficient=True, asked_questions=[])
    master = SimpleNamespace(
        master=SimpleNamespace(classify_intent=AsyncMock(return_value={"intent": "diagnosis"})),
        _create_session=AsyncMock(return_value=SimpleNamespace(id=session_id, context={})),
    )
    diagnostic = SimpleNamespace(
        interview=AsyncMock(return_value=([], state, [], "diagnosis", "")),
        run_full_diagnosis_workflow=AsyncMock(return_value=SimpleNamespace(
            structured_output=SimpleNamespace(model_dump=lambda: report),
            tool_calls_used=[],
        )),
    )
    saved_case = SimpleNamespace(id=case_id)
    save_case = AsyncMock(return_value=saved_case)
    fake_redis = SimpleNamespace(set=AsyncMock(return_value=True))
    monkeypatch.setattr(api, "AgentOrchestrator", Mock(return_value=master))
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "persist_diagnosis_case", save_case)
    monkeypatch.setattr(api, "async_session_maker", fake_db)
    monkeypatch.setattr(redis_client, "get_redis", lambda: fake_redis)

    request = Request({"type": "http", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(user=SimpleNamespace(id=patient_id), is_guest=False, platform="web")
    stream = await api.route_stream(message="合成主诉", request=request, ctx=ctx, db=AsyncMock())
    events = "".join([chunk async for chunk in stream.body_iterator])

    assert save_case.await_count == 1
    assert events.index("event: structured") < events.index("event: complete")
    complete = json.loads(events.split("event: complete")[-1].split("data: ", 1)[1])
    assert complete["case_id"] == str(case_id)
    assert save_case.await_args.kwargs["source_session_id"] == session_id
