"""患者准备包中的语境与原文必须能独立核对。"""
from app.services.case_preparation import build_package, preparation_fingerprint
from types import SimpleNamespace


def source(text, history=None):
    return {"case": {"title": "合成病例", "chief_complaint": text},
            "patient_facts": {"hpi_associated": text}, "raw_answers": {"hpi_associated": text},
            "raw_answer_history": {"hpi_associated": history or [text]},
            "patient_profile": {}, "report": None, "materials": []}


def test_patient_package_keeps_family_current_and_history_separate():
    text = "母亲患有糖尿病；我目前咳嗽3天；既往肺炎已痊愈。"
    package = build_package(source(text), [])
    fact = next(f for f in package["known_facts"] if f["id"] == "patient.reported.hpi_associated")
    spans = fact["clinical_context"]
    assert ["non_patient", "present", "historical"] == [s["status"] for s in spans]
    assert text == fact["value"] == fact["patient_response"]
    assert all(text[s["start"]:s["end"]] == s["text"] for s in spans)
    assert all(s["advisory"] is True for s in spans)


def test_unknown_and_conflicting_originals_are_not_collapsed_by_context():
    unknown = build_package(source("我不清楚是否有药物过敏"), [])
    fact = next(f for f in unknown["unknown_facts"] if f.get("patient_response"))
    assert {"unknown"} == {s["status"] for s in fact["clinical_context"]}
    history = ["测到38.5℃", "我没发过烧，可能记错了"]
    package = build_package(source(history[-1], history), [])
    statements = package["unresolved_facts"][0]["statements"]
    assert history == [s["value"] for s in statements]
    assert all(s["status"] == "needs_review" for row in statements for s in row["clinical_context"])


def test_mixed_subject_and_double_negative_are_withheld_and_policy_invalidates_package(monkeypatch):
    from app.services.clinical_context import annotate_patient_text
    from app.services import case_preparation
    assert "needs_review" == annotate_patient_text("父亲有哮喘我目前没有喘息")[0]["status"]
    assert "uncertain" == annotate_patient_text("我没有否认咳嗽")[0]["status"]
    assert "needs_review" == annotate_patient_text("既往咳嗽现在又出现了")[0]["status"]
    original = preparation_fingerprint(source("目前咳嗽"), [])
    monkeypatch.setattr(case_preparation, "CONTEXT_POLICY_VERSION", "synthetic-next-policy")
    assert original != preparation_fingerprint(source("目前咳嗽"), [])


def test_patient_api_response_marks_old_context_policy_as_stale(monkeypatch):
    from app.api.v1.patient import _preparation_response
    from app.services import case_preparation
    data = source("目前咳嗽3天")
    row = SimpleNamespace(id="synthetic-package", case_id="synthetic-case", version=1, revision=1,
                          state="ready", package=build_package(data, []),
                          source_fingerprint=preparation_fingerprint(data, []), created_at=None, updated_at=None)
    assert _preparation_response(row, data)["is_stale"] is False
    monkeypatch.setattr(case_preparation, "CONTEXT_POLICY_VERSION", "synthetic-next-policy")
    response = _preparation_response(row, data)
    assert response["is_stale"] is True and "needs_reassessment" == response["state"]
