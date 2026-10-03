"""档案状态、旧数据兼容、疾病字段和用药状态的回归。"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.patient_profile import ProfileUpdateRequest
from app.services.patient_profile import profile_records, format_profile_context


def test_legacy_empty_is_not_recorded_and_old_disease_is_chronic():
    profile = SimpleNamespace(allergies=[], chronic_diseases=[{"code": "I10", "name": "合成慢性病"}], current_medications=[], record_metadata={})
    records = profile_records(profile)
    assert records["section_states"]["allergies"] == "not_recorded"
    disease = records["chronic_diseases"][0]
    assert disease["category"] == "chronic"
    assert disease["severity"] == "unknown"
    assert disease["source"] == "legacy_record"
    assert disease["updated_at"] is None


def test_disease_fields_validate_and_source_cannot_be_forged():
    data = ProfileUpdateRequest(chronic_diseases=[{
        "name": "合成特殊疾病", "category": "special", "severity": "severe",
        "diagnosed_date": "2020-01-02", "notes": "患者自报备注", "source": "doctor_verified",
    }])
    record = data.chronic_diseases[0].model_dump(mode="json")
    assert record["category"] == "special"
    assert record["diagnosed_date"] == "2020-01-02"
    assert "source" not in record
    for update in [{"severity": "extreme"}, {"category": "other"}, {"diagnosed_date": str(date.today() + timedelta(days=2))}]:
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(chronic_diseases=[{"name": "合成疾病", **update}])


def test_profile_context_keeps_unknown_and_stopped_separate():
    profile = SimpleNamespace(
        allergies=[], chronic_diseases=[{"name": "合成疾病", "category": "special", "severity": "severe", "diagnosed_date": "2020-01-02", "notes": "合成说明"}],
        current_medications=[{"name": "合成有效药物", "status": "active"}, {"name": "合成停用药物", "status": "stopped"}],
        record_metadata={"sections": {"allergies": {"state": "unknown", "source": "patient_reported", "updated_at": "2026-10-02T00:00:00+00:00"}}},
    )
    records = profile_records(profile)
    assert records["section_states"]["allergies"] == "unknown"
    context = format_profile_context(profile)
    assert "过敏史：未知" in context and "过敏史：明确无" not in context
    assert "合成有效药物" in context.split("已停用药物")[0]
    assert "合成停用药物" in context.split("已停用药物")[1]
    assert "合成说明" in context and "2020-01-02" in context


@pytest.mark.parametrize("state", ["unknown", "not_recorded", "none"])
def test_preparation_preserves_all_profile_states_and_explicit_denial(state):
    from app.services.case_preparation import build_package
    states = dict.fromkeys(["allergies", "conditions", "medications"], state)
    source = {"case": {"id": "synthetic", "title": "合成病例", "chief_complaint": ""},
        "patient_facts": {}, "report": None, "materials": [], "source_session_id": None,
        "patient_profile": {"section_states": states,
            "section_metadata": {section: {"source": "patient_reported"} for section in states}}}
    package = build_package(source, [])
    assert package["profile_record_states"] == states
    if state == "none":
        facts = [item for item in package["known_facts"] if item["id"].startswith("patient.profile.")]
        assert len(facts) == 3
        assert all(item["assertion_status"] == "denied" and item["record_state"] == "none" for item in facts)
        assert not any(item["id"] in {"unknown.allergies", "unknown.conditions", "unknown.medications"} for item in package["unknown_facts"])
    else:
        for fact_id in ["unknown.allergies", "unknown.conditions", "unknown.medications"]:
            fact = next(item for item in package["unknown_facts"] if item["id"] == fact_id)
            assert fact["record_state"] == state


def test_patient_can_confirm_own_legacy_profile_but_not_ai_or_materials():
    from app.api.v1.patient import _confirmable_patient_fact
    legacy = {"id": "patient.profile.allergies", "source_id": "patient_profile.allergies", "source_type": "legacy_record"}
    assert _confirmable_patient_fact(legacy)
    assert not _confirmable_patient_fact({**legacy, "source_type": "ai_inference"})
    assert not _confirmable_patient_fact({**legacy, "source_type": "uploaded_material"})
    assert not _confirmable_patient_fact({**legacy, "active": False})
    assert not _confirmable_patient_fact({**legacy, "source_id": "source_session.report"})
