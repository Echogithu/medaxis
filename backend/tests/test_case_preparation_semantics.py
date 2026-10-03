"""T09：患者未知、否认及先后陈述不能被摘要器混成单一事实。"""

from types import SimpleNamespace

import pytest

from app.models.interview import DynamicInterviewEngine, InterviewState
from app.services.case_preparation import build_package, build_source_snapshot


def _source(
    patient_facts: dict,
    *,
    raw_answers: dict | None = None,
    raw_answer_history: dict | None = None,
    question_texts: dict | None = None,
) -> dict:
    return {
        "case": {
            "id": "synthetic-case",
            "title": "合成病例",
            "chief_complaint": "咳嗽",
            "ai_diagnosis_summary": None,
            "severity": None,
            "is_emergency": False,
        },
        "source_session_id": "synthetic-session",
        "patient_facts": patient_facts,
        "patient_profile": {},
        "raw_answers": raw_answers or {},
        "raw_answer_history": raw_answer_history or {},
        "question_texts": question_texts or {},
        "report": None,
        "materials": [],
    }


@pytest.mark.parametrize("answer", ["不清楚", "不记得", "未知", "不知道", "跳过"])
def test_uncertain_allergy_answers_remain_unknown_and_preserve_patient_words(answer: str) -> None:
    original = "过敏史我真的不清楚，以前没有专门检查过。"
    package = build_package(
        _source(
            {"pmh_allergy": answer},
            raw_answers={"pmh_allergy": original},
            raw_answer_history={"pmh_allergy": [original]},
        ),
        [],
    )

    assert not any(fact["id"] == "patient.reported.pmh_allergy" for fact in package["known_facts"])
    allergy = next(fact for fact in package["unknown_facts"] if fact["id"] == "unknown.allergies")
    assert allergy["status"] == "unknown"
    assert allergy["answer_status"] == "unknown"
    assert allergy["patient_response"] == original
    assert allergy["patient_response_history"] == [original]


@pytest.mark.parametrize(
    ("answer", "assertion_status"),
    [("无", "denied"), ("明确否认", "denied"), ("有", "affirmed"), ("青霉素过敏", "reported")],
)
def test_explicit_allergy_denial_and_affirmation_remain_distinct(
    answer: str, assertion_status: str
) -> None:
    package = build_package(_source({"pmh_allergy": answer}), [])

    fact = next(fact for fact in package["known_facts"] if fact["id"] == "patient.reported.pmh_allergy")
    assert fact["value"] == answer
    assert fact["assertion_status"] == assertion_status
    assert "unknown.allergies" not in {item["id"] for item in package["unknown_facts"]}


def test_unknown_onset_preserves_original_answer_without_inventing_a_date() -> None:
    original = "我不记得哪天开始。"
    package = build_package(
        _source(
            {"hpi_onset": "不记得", "hpi_quality": "干咳无痰"},
            raw_answers={"hpi_onset": original},
            raw_answer_history={"hpi_onset": [original]},
        ),
        [],
    )

    assert not any(fact["id"] == "patient.reported.hpi_onset" for fact in package["known_facts"])
    onset = next(fact for fact in package["unknown_facts"] if fact["id"] == "unknown.hpi_onset")
    assert onset["patient_response"] == original
    assert not any("前" in str(fact.get("value", "")) for fact in package["known_facts"])


def test_multiple_patient_answers_are_kept_unresolved_instead_of_selecting_latest() -> None:
    first = "晚上量过体温 38.5℃。"
    second = "我没发过烧，可能是记错了。"
    package = build_package(
        _source(
            {"hpi_associated": "无发热"},
            raw_answers={"hpi_associated": second},
            raw_answer_history={"hpi_associated": [first, second]},
            question_texts={"hpi_associated": "是否发热？"},
        ),
        [],
    )

    assert not any(fact["id"] == "patient.reported.hpi_associated" for fact in package["known_facts"])
    unresolved = package["unresolved_facts"]
    assert len(unresolved) == 1
    assert unresolved[0]["status"] == "needs_reconciliation"
    assert unresolved[0]["label"] == "是否发热？"
    assert [item["value"] for item in unresolved[0]["statements"]] == [first, second]
    assert all(item["source_type"] == "patient_reported" for item in unresolved[0]["statements"])


def test_source_snapshot_carries_patient_answer_history_and_question_labels() -> None:
    original_answers = {"hpi_associated": ["测到 38.5℃。", "我没发过烧。"]}
    session = SimpleNamespace(
        id="synthetic-session",
        context={"interview": {
            "collected_info": {"hpi_associated": "无发热"},
            "raw_answers": {"hpi_associated": "我没发过烧。"},
            "raw_answer_history": original_answers,
            "question_texts": {"hpi_associated": "是否发热？"},
        }},
        structured_output=None,
    )
    case = SimpleNamespace(
        id="synthetic-case",
        title="合成病例",
        chief_complaint="发热？",
        ai_diagnosis_summary=None,
        severity=None,
        is_emergency=False,
    )

    snapshot = build_source_snapshot(case, session, [], None)

    assert snapshot["raw_answer_history"] == original_answers
    package = build_package(snapshot, [])
    assert package["unresolved_facts"][0]["label"] == "是否发热？"
    assert [item["value"] for item in package["unresolved_facts"][0]["statements"]] == original_answers[
        "hpi_associated"
    ]


class _JsonResponseLLM:
    async def chat(self, **_kwargs):
        return SimpleNamespace(content="{}")


@pytest.mark.asyncio
async def test_interview_state_persists_ordered_raw_answer_history() -> None:
    state = InterviewState()
    engine = DynamicInterviewEngine(_JsonResponseLLM())
    first = "晚上量过体温 38.5℃。"
    second = "我没发过烧，可能是记错了。"

    await engine.process_answer(state, "hpi_associated", first)
    await engine.process_answer(state, "hpi_associated", second)

    assert state.raw_answers["hpi_associated"] == second
    assert state.raw_answer_history["hpi_associated"] == [first, second]
    assert first in state.get_summary()
    assert second in state.get_summary()
    assert "hpi_associated: " not in state.get_summary()
    assert InterviewState.from_dict(state.to_dict()).raw_answer_history == state.raw_answer_history


@pytest.mark.asyncio
async def test_unknown_interview_answer_remains_explicit_in_diagnosis_summary() -> None:
    state = InterviewState()
    await DynamicInterviewEngine(_JsonResponseLLM()).process_answer(
        state, "pmh_allergy", "不清楚"
    )

    summary = state.get_summary()
    assert "患者尚未确认 [pmh_allergy]（仍为未知）: 不清楚" in summary
    assert "pmh_allergy: 不清楚" not in summary


@pytest.mark.asyncio
async def test_natural_language_unknown_answer_stays_unknown_in_summary_and_package() -> None:
    answer = "我不记得哪天开始。"
    state = InterviewState()

    await DynamicInterviewEngine(_JsonResponseLLM()).process_answer(
        state, "hpi_onset", answer
    )
    summary = state.get_summary()
    package = build_package(
        _source(
            state.collected_info,
            raw_answers=state.raw_answers,
            raw_answer_history=state.raw_answer_history,
        ),
        [],
    )

    assert "患者尚未确认 [hpi_onset]（仍为未知）: 我不记得哪天开始。" in summary
    assert not any(fact["id"] == "patient.reported.hpi_onset" for fact in package["known_facts"])
    onset = next(fact for fact in package["unknown_facts"] if fact["id"] == "unknown.hpi_onset")
    assert onset["patient_response"] == answer
