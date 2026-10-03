"""在实际编排入口验证患者信息复用与停止状态；不连接真实模型/数据库。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.interview import DynamicInterviewEngine, InterviewState
from app.services.llm import LLMResponse
from app.services.orchestrator import InterviewGenerationError, InterviewOrchestrator, Track1Agent


def model_response(data):
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="synthetic",
                       provider="synthetic", usage_prompt_tokens=0, usage_completion_tokens=0,
                       finish_reason="stop")


@pytest.mark.asyncio
async def test_已发出的卡片未回答时不能结束问诊或生成新题():
    state = InterviewState(
        chief_complaint="合成主诉",
        asked_questions=["hpi_onset"],
        question_texts={"hpi_onset": "您什么时候开始不舒服？"},
        pending_question_ids=["hpi_onset"],
    )
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({"basic_module": []})))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)

    assert "ask" == action
    assert [] == cards
    assert ["hpi_onset"] == state.pending_question_ids
    assert not state.is_sufficient
    llm.chat.assert_not_awaited()


def question(key, text, **metadata):
    return {"question_id": key, "question": text, "type": "choice",
            "options": ["有", "没有", "不清楚"], "phase": key, **metadata}


@pytest.mark.asyncio
async def test_已采集信息不重复问且每轮默认只出一题():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"pmh_allergy": "明确无"})
    data = {"basic_module": [question("pmh_allergy", "您有过敏史吗？"),
                              question("hpi_onset", "您什么时候开始不舒服？"),
                              question("ps_occupation", "您的职业是什么？", priority="optional")]}
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response(data)))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
    assert ["hpi_onset"] == [card.question_id for card in cards]
    assert "ask" == action


@pytest.mark.asyncio
async def test_患者已回答未知时不换编号重问且摘要保留未知():
    state = InterviewState(chief_complaint="合成主诉")
    engine = DynamicInterviewEngine(SimpleNamespace(chat=AsyncMock()))
    state = await engine.process_answer(state, "pmh_allergy", "不清楚")
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({
        "basic_module": [question("pmh_allergy_002", "您是否对药物过敏？")],
    })))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
    assert [] == cards
    assert "synthesize" == action
    assert not state.is_sufficient
    assert any("pmh_allergy" in gap for gap in state.information_gaps)
    assert "仍为未知" in state.get_summary()


@pytest.mark.asyncio
async def test_建议轮数用完仍继续询问下一项必要信息():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"hpi_onset": "昨天"}, interview_rounds=6)
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({
        "basic_module": [question("hpi_severity", "严重程度如何？")],
    })))
    cards, state, _, action, _ = await InterviewOrchestrator(llm).decide_next(state)
    assert ["hpi_severity"] == [card.question_id for card in cards]
    assert "ask" == action
    assert "" == state.stop_reason
    assert not state.is_sufficient
    assert "interviewing" == state.phase


@pytest.mark.asyncio
async def test_补问模型失败不转为充分或成功摘要():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"hpi_onset": "昨天"})
    llm = SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError("synthetic failure")))
    with pytest.raises(InterviewGenerationError):
        await InterviewOrchestrator(llm).decide_next(state)
    assert "interviewing" == state.phase
    assert not state.is_sufficient


@pytest.mark.asyncio
async def test_原文抽取保留否定范围且拒绝亲属及编造事实():
    state = InterviewState(chief_complaint="我无发热，母亲患高血压")
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({
        "basic_module": [question("hpi_onset", "什么时候开始不舒服？")],
        "known_information": [
            {"information_key": "hpi_associated", "quote": "发热", "source": "chief_complaint"},
            {"information_key": "pmh_chronic", "quote": "高血压", "source": "chief_complaint"},
            {"information_key": "pmh_allergy", "quote": "青霉素过敏", "source": "chief_complaint"},
        ],
    })))
    await Track1Agent(llm).generate(state)
    assert "我无发热" == state.known_information["hpi_associated"][0]["quote"]
    assert "not_recorded" == state.information_status("pmh_chronic")
    assert "not_recorded" == state.information_status("pmh_allergy")


def test_旧会话恢复未知且冲突只允许核对一次():
    state = InterviewState.from_dict({"chief_complaint": "合成", "raw_answers": {"pmh_allergy": "不清楚"}})
    state.refresh_known_information()
    assert "unknown" == state.information_status("pmh_allergy")
    state.remember_information("med_current", "正在服用", "answer")
    state.remember_information("med_current", "已经停用", "answer")
    from app.models.interview import QuestionTemplate
    q = QuestionTemplate(question_id="med_current_2", information_key="med_current", question="请核对用药", type="choice",
                         priority="clarification", reason="前后用药记录需核对")
    assert [q] == InterviewOrchestrator._deduplicate([q], state)
    state.clarification_keys = ["med_current"]
    assert [] == InterviewOrchestrator._deduplicate([q], state)


def test_所有历史维度进入提示不截掉较早信息():
    state = InterviewState(collected_info={f"legacy_{i}": f"original_{i}" for i in range(20)})
    prompt = Track1Agent(SimpleNamespace())._build_prompt(state, None)
    assert "original_0" in prompt and "original_19" in prompt


@pytest.mark.asyncio
async def test_真实响应中的已有采集值和患者回答来源可解析且校验原文():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"hpi_onset": "昨天"},
                           raw_answers={"pmh_allergy": "不清楚"})
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({
        "basic_module": [question("hpi_quality", "是什么感觉？")],
        "known_information": [
            {"information_key": "hpi_onset", "quote": "昨天", "source": "collected_info"},
            {"information_key": "pmh_allergy", "quote": "不清楚", "source": "answer"},
            {"information_key": "med_current", "quote": "已经服药", "source": "answer"},
        ],
    })))
    await Track1Agent(llm).generate(state)
    assert "collected_info" == state.known_information["hpi_onset"][0]["source"]
    assert "unknown" == state.information_status("pmh_allergy")
    assert "not_recorded" == state.information_status("med_current")


@pytest.mark.asyncio
async def test_连续未知不重复追问但仍询问其他未问必要项():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"hpi_onset": "不清楚"})
    llm = SimpleNamespace(chat=AsyncMock())
    orchestrator = InterviewOrchestrator(llm)
    engine = DynamicInterviewEngine(llm)
    for key in ["hpi_quality", "hpi_location", "hpi_severity"]:
        llm.chat.return_value = model_response({"basic_module": [question(key, key)]})
        cards, state, _, action, _ = await orchestrator.decide_next(state)
        if cards:
            state = await engine.process_answer(state, cards[0].question_id, "不清楚")
    assert ["hpi_severity"] == [card.question_id for card in cards]
    assert "ask" == action
    assert "" == state.stop_reason
    assert 3 == state.interview_rounds
    assert not state.is_sufficient
    assert "unknown" == state.information_status("hpi_severity")


@pytest.mark.asyncio
async def test_年龄月龄从授权患者资料传入但不推断缺失值():
    import uuid
    from app.api.v1.agents import _load_health_profile_context
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), get=AsyncMock(return_value=SimpleNamespace(age_years=0, age_months=5)))
    text = await _load_health_profile_context(db, str(uuid.uuid4()))
    assert "0岁" in text and "5个月" in text
    assert "未获医护核验" in text


@pytest.mark.asyncio
async def test_真实模型返回缺口对象却拒绝生成问题时不能成功结束():
    state = InterviewState(chief_complaint="合成主诉", collected_info={"hpi_onset": "昨天"})
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({"action": "synthesize", "basic_module": [],
        "needs_more_info": [{"information_key": "hpi_quality", "reason": "症状性质待核对"}]})))
    with pytest.raises(InterviewGenerationError):
        await InterviewOrchestrator(llm).decide_next(state)
    assert 2 == llm.chat.await_count
    assert "interviewing" == state.phase
    assert not state.is_sufficient
    assert ["hpi_quality：症状性质待核对"] == state.information_gaps


def test_损坏缺口对象不能静默省略():
    from app.models.interview import InterviewDecision
    with pytest.raises(ValueError):
        InterviewDecision.model_validate({"needs_more_info": [{"information_key": "hpi_quality"}]})


@pytest.mark.asyncio
async def test_明确澄清更新当前自报值但保留冲突历史且新变化重新待核对():
    state = InterviewState(chief_complaint="合成")
    state.record_patient_answer("med_current", "正在服药")
    state.record_patient_answer("med_current", "已经停药")
    llm = SimpleNamespace(chat=AsyncMock(return_value=model_response({"basic_module": [
        question("med_current_2", "请核对目前用药", information_key="med_current", priority="clarification", reason="核对冲突")]})))
    cards, state, *_ = await InterviewOrchestrator(llm).decide_next(state)
    assert 1 == len(cards)
    state.record_patient_answer(cards[0].question_id, "目前已经停药")
    state.refresh_known_information()
    state.refresh_information_gaps()
    assert "reported" == state.information_status("med_current")
    assert [] == state.information_gaps
    assert "正在服药" in state.get_summary() and "已经停药" in state.get_summary()
    assert "患者本次核对回答（仍为自报）: 目前已经停药" in state.get_summary()
    restored = InterviewState.from_dict(state.to_dict())
    assert "reported" == restored.information_status("med_current")
    restored.record_patient_answer("med_current", "今天重新开始服药")
    assert "needs_review" == restored.information_status("med_current")


def test_未知及假设性的澄清不能消除冲突():
    state = InterviewState()
    state.record_patient_answer("med_current", "正在服药")
    state.record_patient_answer("med_current", "已经停药")
    state.clarification_question_ids["med_current_2"] = "med_current"
    state.question_phase_keys["med_current_2"] = "med_current"
    for answer in ["不清楚", "如果停药就好了", "可能已停药"]:
        state.record_patient_answer("med_current_2", answer)
        assert "needs_review" == state.information_status("med_current")
