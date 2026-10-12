"""复现换标识重复题被去重后，未问必要项无法补生成的真实失败模式。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.interview import InterviewState
from app.services.llm import LLMResponse
from app.services.orchestrator import InterviewGenerationError, InterviewOrchestrator, Track1Agent


def response(data):
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model='synthetic', provider='synthetic',
                       finish_reason='stop', usage_prompt_tokens=0, usage_completion_tokens=0)


def state():
    s=InterviewState(chief_complaint='合成：已按医嘱服药，具体检验不清楚',
                     asked_questions=['adv_old_tests'], question_texts={'adv_old_tests':'能提供具体检验报告吗？'},
                     question_phase_keys={'adv_old_tests':'adv_old_tests'})
    s.record_patient_answer('adv_old_tests','不清楚')
    return s


def duplicate():
    return {'basic_module':[{'question_id':'adv_new_tests','information_key':'adv_new_tests',
                            'question':'能提供哪些检查结果？','type':'choice','options':['有报告','不清楚'],
                            'reason':'核对检查依据'}], 'needs_more_info':['adv_new_tests：检查依据待核对']}


@pytest.mark.asyncio
async def test_语义重复候选被删除后有一次针对必要缺口的补生成机会():
    recovered={'basic_module':[{'question_id':'med_dose','information_key':'med_dose',
                               'question':'您清楚实际服药剂量吗？','type':'choice','options':['清楚','不清楚'],
                               'reason':'评估实际用药暴露'}], 'needs_more_info':['med_dose：实际剂量待核对']}
    llm=SimpleNamespace(chat=AsyncMock(side_effect=[response(duplicate()), response({'drop':[1]}),
                                                    response(recovered), response({'drop':[]})]))
    cards,s,_,action,_=await InterviewOrchestrator(llm).decide_next(state())
    assert ['med_dose']==[q.question_id for q in cards]
    assert 'ask'==action
    assert not s.is_sufficient and 'interviewing'==s.phase
    assert 4==llm.chat.await_count
    assert '必须继续询问的缺口' in llm.chat.call_args_list[2].kwargs['messages'][0]['content']


@pytest.mark.asyncio
async def test_补生成仍重复时显式失败且不能跳过必要缺口():
    llm=SimpleNamespace(chat=AsyncMock(side_effect=[response(duplicate()),response({'drop':[1]}),
                                                    response(duplicate()),response({'drop':[1]})]))
    s=state()
    with pytest.raises(InterviewGenerationError):
        await InterviewOrchestrator(llm).decide_next(s)
    assert 4==llm.chat.await_count
    assert 'interviewing'==s.phase and not s.is_sufficient
    assert ['adv_old_tests']==s.asked_questions


def test_生成提示包含已问问题原文稳定标识及未知回答():
    prompt=Track1Agent(SimpleNamespace())._build_prompt(state(), None)
    assert '能提供具体检验报告吗？' in prompt
    assert 'adv_old_tests' in prompt and '不清楚' in prompt
