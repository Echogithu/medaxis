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


def empty_profile_db():
    # 路由回归默认患者尚未建档；档案传递另由专门测试验证。
    return AsyncMock(scalar=AsyncMock(return_value=None))


def profile_chain_db():
    profile = SimpleNamespace(allergies=[], chronic_diseases=[{
        "name": "档案链路合成特殊疾病", "category": "special", "severity": "severe",
        "diagnosed_date": "2020-01-02", "notes": "链路自报说明",
    }], current_medications=[{"name": "链路停用药", "status": "stopped"}], record_metadata={})
    return AsyncMock(scalar=AsyncMock(return_value=profile))


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
    stream = await api.route_stream(req=api.RouteStreamRequest(message="头疼还发烧"), request=request, ctx=ctx, db=empty_profile_db())
    events = "".join([chunk async for chunk in stream.body_iterator])
    assert "event: error" in events
    assert "event: structured" not in events
    error_data = events.rsplit("event: error\n", 1)[1].split("data: ", 1)[1].split("\n", 1)[0]
    error_payload = json.loads(error_data)
    expected_code = (
        "INTERVIEW_GENERATION_FAILED"
        if isinstance(failure, InterviewGenerationError)
        else "LLM_INTERNAL_ERROR"
    )
    assert error_payload["code"] == expected_code
    if str(failure):
        assert str(failure) not in error_payload["error"]
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
    stream = await api.route_stream(req=api.RouteStreamRequest(message="合成主诉"), request=request, ctx=ctx, db=profile_chain_db())
    events = "".join([chunk async for chunk in stream.body_iterator])

    assert save_case.await_count == 1
    assert events.index("event: structured") < events.index("event: complete")
    complete = json.loads(events.split("event: complete")[-1].split("data: ", 1)[1])
    assert complete["case_id"] == str(case_id)
    assert save_case.await_args.kwargs["source_session_id"] == session_id
    for call in [diagnostic.interview.await_args, diagnostic.run_full_diagnosis_workflow.await_args]:
        assert "档案链路合成特殊疾病" in call.kwargs["patient_history"]
        assert "已停用药物" in call.kwargs["patient_history"]
        assert "2020-01-02" in call.kwargs["patient_history"]


@pytest.mark.asyncio
async def test_stream_does_not_publish_report_when_case_persistence_fails(monkeypatch):
    from app.api.v1 import agents as api
    from app.db import redis_client

    session_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    report = {"primary_diagnosis": "合成演示报告", "confidence": "low"}
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
    save_case = AsyncMock(side_effect=api.DiagnosisCasePersistenceError("synthetic database detail"))
    monkeypatch.setattr(api, "AgentOrchestrator", Mock(return_value=master))
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "persist_diagnosis_case", save_case)
    monkeypatch.setattr(api, "async_session_maker", fake_db)
    monkeypatch.setattr(redis_client, "get_redis", lambda: SimpleNamespace(set=AsyncMock(return_value=True)))

    request = Request({"type": "http", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(user=SimpleNamespace(id=patient_id), is_guest=False, platform="web")
    stream = await api.route_stream(req=api.RouteStreamRequest(message="合成主诉"), request=request, ctx=ctx, db=empty_profile_db())
    events = "".join([chunk async for chunk in stream.body_iterator])

    save_case.assert_awaited_once()
    assert save_case.await_args.kwargs["patient_id"] == patient_id
    assert save_case.await_args.kwargs["source_session_id"] == session_id
    assert "event: structured" not in events
    assert "event: complete" not in events
    error_payload = json.loads(events.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert error_payload["code"] == "CASE_PERSISTENCE_FAILED"
    assert "synthetic database detail" not in error_payload["error"]


@pytest.mark.asyncio
async def test_stream_stops_when_diagnosis_session_cannot_be_created(monkeypatch):
    from app.api.v1 import agents as api

    patient_id = uuid.uuid4()
    report = {"primary_diagnosis": "合成演示报告", "confidence": "low"}
    master = SimpleNamespace(
        master=SimpleNamespace(classify_intent=AsyncMock(return_value={"intent": "diagnosis"})),
        _create_session=AsyncMock(return_value=None),
    )
    diagnostic = SimpleNamespace(
        interview=AsyncMock(),
        run_full_diagnosis_workflow=AsyncMock(),
        analyze=AsyncMock(return_value=SimpleNamespace(
            structured_output=SimpleNamespace(model_dump=lambda: report),
            tool_calls_used=[],
            content="合成诊断文本",
        )),
    )
    monkeypatch.setattr(api, "AgentOrchestrator", Mock(return_value=master))
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "async_session_maker", fake_db)

    request = Request({"type": "http", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(user=SimpleNamespace(id=patient_id), is_guest=False, platform="web")
    stream = await api.route_stream(req=api.RouteStreamRequest(message="合成主诉"), request=request, ctx=ctx, db=empty_profile_db())
    events = "".join([chunk async for chunk in stream.body_iterator])

    diagnostic.analyze.assert_not_awaited()
    assert "event: structured" not in events
    assert "event: complete" not in events
    error_payload = json.loads(events.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert error_payload["code"] == "DIAGNOSIS_SESSION_CREATION_FAILED"


@pytest.mark.asyncio
async def test_continue_completed_session_does_not_confirm_unsaved_case(monkeypatch):
    from app.api.v1 import agents as api
    from app.db import redis_client

    session_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id,
        user_id=patient_id,
        structured_output={"primary_diagnosis": "合成演示报告", "confidence": "low", "knowledge_citations": [{"citation_id": "S1"}]},
    )
    db = empty_profile_db()
    db.get = AsyncMock(return_value=session)
    diagnostic = SimpleNamespace(
        interview_answer=AsyncMock(return_value=([], SimpleNamespace(
            asked_questions=[], is_sufficient=True, phase="completed", red_flags_detected=[]
        ), [], "completed", "")),
        run_full_diagnosis_workflow=AsyncMock(),
    )
    save_case = AsyncMock(side_effect=api.DiagnosisCasePersistenceError("synthetic database detail"))
    monkeypatch.setattr(api, "_require_session_access", AsyncMock())
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "persist_diagnosis_case", save_case)
    monkeypatch.setattr(redis_client, "get_redis", lambda: SimpleNamespace(exists=AsyncMock(return_value=False)))

    request = Request({"type": "http", "method": "GET", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(user=SimpleNamespace(id=patient_id), is_guest=False, platform="web")
    stream = await api.route_stream_continue(
        request=request,
        ctx=ctx,
        session_id=str(session_id),
        question_id="hpi_onset",
        db=db,
    )
    events = "".join([chunk async for chunk in stream.body_iterator])

    save_case.assert_awaited_once()
    assert "event: structured" not in events
    assert "event: complete" not in events
    error_payload = json.loads(events.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert error_payload["code"] == "CASE_PERSISTENCE_FAILED"
    assert "synthetic database detail" not in error_payload["error"]
    diagnostic.run_full_diagnosis_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_diagnosis_does_not_publish_report_when_case_persistence_fails(monkeypatch):
    from app.api.v1 import agents as api
    from app.db import redis_client

    session_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    session = SimpleNamespace(id=session_id, user_id=patient_id, structured_output=None)
    state = SimpleNamespace(is_sufficient=True, phase="completed", red_flags_detected=[], asked_questions=[])
    diagnostic = SimpleNamespace(
        interview_answer=AsyncMock(return_value=([], state, [], "diagnosis", "")),
        run_full_diagnosis_workflow=AsyncMock(return_value=SimpleNamespace(
            structured_output=SimpleNamespace(model_dump=lambda: {"primary_diagnosis": "合成演示报告"}),
            tool_calls_used=[],
        )),
    )
    db = profile_chain_db()
    db.get = AsyncMock(return_value=session)
    save_case = AsyncMock(side_effect=api.DiagnosisCasePersistenceError("synthetic database detail"))
    monkeypatch.setattr(api, "_require_session_access", AsyncMock())
    monkeypatch.setattr(api, "DiagnosisAgent", Mock(return_value=diagnostic))
    monkeypatch.setattr(api, "persist_diagnosis_case", save_case)
    monkeypatch.setattr(redis_client, "get_redis", lambda: SimpleNamespace(
        exists=AsyncMock(return_value=False), set=AsyncMock(return_value=True)
    ))

    request = Request({"type": "http", "method": "GET", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(user=SimpleNamespace(id=patient_id), is_guest=False, platform="web")
    stream = await api.route_stream_continue(
        request=request,
        ctx=ctx,
        session_id=str(session_id),
        question_id="hpi_onset",
        db=db,
    )
    events = "".join([chunk async for chunk in stream.body_iterator])

    save_case.assert_awaited_once()
    assert save_case.await_args.kwargs["patient_id"] == patient_id
    assert save_case.await_args.kwargs["source_session_id"] == session_id
    for call in [diagnostic.interview_answer.await_args, diagnostic.run_full_diagnosis_workflow.await_args]:
        assert "档案链路合成特殊疾病" in call.kwargs["patient_history"]
        assert "链路自报说明" in call.kwargs["patient_history"]
    assert "event: structured" not in events
    assert "event: complete" not in events
    error_payload = json.loads(events.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert error_payload["code"] == "CASE_PERSISTENCE_FAILED"
    assert "synthetic database detail" not in error_payload["error"]


async def _post_diagnosis_chat_stream(monkeypatch, llm):
    from app.api.v1 import agents as api

    parent_id = uuid.uuid4()
    user_id = uuid.uuid4()
    parent = SimpleNamespace(
        id=parent_id,
        user_id=user_id,
        guest_session_id=None,
        context={"interview": {"phase": "completed"}},
    )
    db = empty_profile_db()
    db.get = AsyncMock(return_value=parent)
    db.add = Mock()
    monkeypatch.setattr(api, "async_session_maker", fake_db)
    monkeypatch.setattr(api, "_build_chat_context", AsyncMock(return_value="合成测试上下文"))
    monkeypatch.setattr(api, "LLMService", Mock(return_value=llm))
    request = Request({"type": "http", "query_string": b"", "headers": []})
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        is_guest=False,
        guest_id=None,
        platform="web",
    )
    stream = await api.chat_session(
        session_id=str(parent_id),
        req=api.ChatRequest(message="请解释刚才的报告"),
        request=request,
        ctx=ctx,
        db=db,
    )
    return api, stream, db


@pytest.mark.asyncio
async def test_post_diagnosis_empty_response_has_stable_error_and_failed_child(monkeypatch):
    llm = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(
        content="", model="test", provider="test", usage_prompt_tokens=1,
        usage_completion_tokens=0, finish_reason="stop",
    )))
    api, stream, db = await _post_diagnosis_chat_stream(monkeypatch, llm)

    events = "".join([chunk async for chunk in stream.body_iterator])
    payload = json.loads(events.rsplit("event: error\n", 1)[1].split("data: ", 1)[1].split("\n", 1)[0])
    child = db.add.call_args.args[0]

    assert payload["code"] == "LLM_EMPTY_RESPONSE"
    assert "complete" not in events
    assert child.status == api.AgentSessionStatus.FAILED


@pytest.mark.asyncio
async def test_post_diagnosis_cancellation_marks_child_failed_and_propagates(monkeypatch):
    llm = SimpleNamespace(chat=AsyncMock(side_effect=asyncio.CancelledError()))
    api, stream, db = await _post_diagnosis_chat_stream(monkeypatch, llm)

    with pytest.raises(asyncio.CancelledError):
        _ = [chunk async for chunk in stream.body_iterator]

    child = db.add.call_args.args[0]
    assert child.status == api.AgentSessionStatus.FAILED
    assert 2 <= db.commit.await_count


@pytest.mark.asyncio
async def test_track1_does_not_promote_explicitly_denied_symptoms_to_red_flags():
    data = questions()
    data["red_flags"] = [
        "目前无发热", "无外伤", "无呕吐", "无视力改变", "无肢体无力", "无言语问题",
    ]
    llm = SimpleNamespace(chat=AsyncMock(return_value=response(data)))

    _, _, flags, _ = await Track1Agent(llm).generate(
        InterviewState(chief_complaint="synthetic mild headache")
    )

    assert flags == []


@pytest.mark.asyncio
async def test_track1_keeps_explicit_positive_emergency_signs():
    data = questions()
    data["red_flags"] = ["突然意识丧失", "频繁呕吐无法进食", "无呼吸"]
    llm = SimpleNamespace(chat=AsyncMock(return_value=response(data)))

    _, _, flags, _ = await Track1Agent(llm).generate(
        InterviewState(chief_complaint="synthetic emergency scenario")
    )

    assert flags == data["red_flags"]
