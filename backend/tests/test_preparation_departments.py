"""通用科室参考只说明咨询方向，不能把 AI 诊断当作患者事实。"""

import pytest

from app.services.case_preparation import build_package, preparation_fingerprint


def source(complaint="咳嗽持续三天", **case_fields):
    return {
        "case": {"id": "synthetic", "title": "合成病例", "chief_complaint": complaint,
                 "is_emergency": False, **case_fields},
        "patient_facts": {}, "patient_profile": {}, "report": {}, "materials": [],
    }


def test_patient_can_get_a_traceable_respiratory_consultation_reference():
    package = build_package(source(), [])
    department = package["department"]
    assert "consultation_reference" == department["status"]
    assert "呼吸内科" == department["recommendation"]
    assert ["patient.chief_complaint"] == department["evidence_ids"]
    assert department["references"][0]["url"].startswith("https://www.sysu6h.cn/")
    assert "未经临床审核" in department["scope_note"]


@pytest.mark.parametrize("complaint, expected", [
    ("腹泻两天", "消化内科"), ("牙疼", "口腔科"), ("尿频", "泌尿专科"),
    ("皮肤瘙痒", "皮肤科"), ("眼睛流泪", "眼科"), ("鼻塞", "耳鼻喉科"),
    ("关节痛", "骨科"), ("月经失调", "妇产科"),
])
def test_common_complaints_have_limited_consultation_directions(complaint, expected):
    assert expected == build_package(source(complaint), [])["department"]["recommendation"]


@pytest.mark.parametrize("complaint", ["没有咳嗽", "是否咳嗽我不确定", "以前咳嗽现在好了", "父亲咳嗽", "孩子咳嗽", "孕期咳嗽"])
def test_denied_uncertain_historical_and_special_context_do_not_get_auto_specialty(complaint):
    package = build_package(source(complaint), [])
    assert None is package["department"]["recommendation"]
    assert "导诊" in package["department"]["reason"]


def test_negative_associated_clause_does_not_become_a_positive_symptom():
    assert "消化内科" == build_package(source("腹泻，没有咳嗽"), [])["department"]["recommendation"]


def test_multiple_directions_offer_one_focus_question_instead_of_arbitrary_ranking():
    package = build_package(source("咳嗽和腹泻"), [])
    assert "needs_clarification" == package["department"]["status"]
    assert None is package["department"]["recommendation"]
    assert "unknown.department_focus" in {fact["id"] for fact in package["unknown_facts"]}
    chosen = build_package(source("咳嗽和腹泻"), [
        {"fact_id": "unknown.department_focus", "value": "腹泻、便秘、反酸等消化相关问题"},
    ])
    assert "消化内科" == chosen["department"]["recommendation"]
    assert ["correction.unknown.department_focus"] == chosen["department"]["evidence_ids"]


def test_corrected_complaint_is_used_without_changing_source():
    original = source("咳嗽")
    result = build_package(original, [{"fact_id": "patient.chief_complaint", "value": "牙痛"}])
    assert "口腔科" == result["department"]["recommendation"]
    assert "咳嗽" == original["case"]["chief_complaint"]


@pytest.mark.parametrize("complaint", ["胸痛伴咳嗽", "腹泻伴便血", "突然视力下降", "咳嗽越来越严重"])
def test_risk_descriptions_do_not_get_routine_department_even_after_focus_choice(complaint):
    result = build_package(source(complaint), [{"fact_id": "unknown.department_focus", "value": "respiratory"}])
    assert "risk_review" == result["department"]["status"]
    assert None is result["department"]["recommendation"]


def test_existing_risk_and_emergency_flags_precede_consultation_references():
    original = source()
    original["report"] = {"red_flags": ["合成风险提示"]}
    assert "risk_review" == build_package(original, [])["department"]["status"]
    original["case"]["is_emergency"] = True
    urgent = build_package(original, [])["department"]
    assert "urgent" == urgent["status"]
    assert None is urgent["recommendation"]


def test_high_severity_without_text_flags_still_requires_medical_triage():
    original = source(severity="high")
    assert "risk_review" == build_package(original, [])["department"]["status"]


def test_ai_diagnosis_cannot_supply_a_department_match():
    original = source("想了解体检报告")
    original["report"] = {"primary_diagnosis": "腹泻", "key_findings": ["咳嗽"]}
    assert "general_consultation" == build_package(original, [])["department"]["status"]


def test_conflicting_patient_answers_require_reconciliation_before_auto_reference():
    original = source()
    original["raw_answer_history"] = {"hpi_quality": ["咳嗽", "没有咳嗽"]}
    assert "needs_clarification" == build_package(original, [])["department"]["status"]


def test_policy_version_invalidates_old_source_only_fingerprint():
    from app.services.case_preparation import canonical_fingerprint
    original = source()
    assert preparation_fingerprint(original, []) != canonical_fingerprint({"source": original, "patient_corrections": []})
