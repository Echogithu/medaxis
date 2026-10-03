"""Validate the patient-smoke catalog and optionally run mapped engineering tests.

This script never invents live-model results. Catalog existence is not a passing score.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("API_KEY_MASTER_KEY", "test-master-key-32bytes-long!!!")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32bytes-long!!!")
ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
TEMPLATE_PATH = Path(__file__).resolve().parent / "results.template.json"
EXPECTED_IDS = [f"SM-{i:02d}" for i in range(1, 11)]
REQUIRED_CASE_KEYS = {
    "id",
    "title",
    "family",
    "priority",
    "pf",
    "modes",
    "personas",
    "script",
    "required_facts",
    "unknown_facts",
    "forbidden_inferences",
    "expected",
    "mapped_tests",
    "evidence_status",
}
ALLOWED_MODES = {"engineering", "live_model", "human_review", "substitute_demo"}
ALLOWED_TEST_KINDS = {"pytest", "e2e_script", "catalog_contract"}
SCORE_FIELDS = [
    "flow_complete",
    "unknown_preserved",
    "contradiction_surfaced",
    "no_hallucinated_citation",
    "schema_ok",
    "case_bound",
    "recoverable",
    "no_false_success",
    "isolation_ok",
    "latency_ms",
    "token_cost",
]


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cases = catalog.get("cases")
    _require(catalog.get("status") == "DEFINED_NOT_RUN", "catalog.status must remain DEFINED_NOT_RUN until a dated run is recorded", errors)
    _require(isinstance(cases, list) and len(cases) == 10, f"expected 10 cases, got {0 if not isinstance(cases, list) else len(cases)}", errors)
    if not isinstance(cases, list):
        return errors

    ids = [case.get("id") for case in cases]
    _require(ids == EXPECTED_IDS, f"case ids must be {EXPECTED_IDS}, got {ids}", errors)
    _require(len(set(ids)) == len(ids), "case ids must be unique", errors)

    for case in cases:
        cid = case.get("id", "<missing>")
        missing = REQUIRED_CASE_KEYS - set(case)
        _require(not missing, f"{cid}: missing keys {sorted(missing)}", errors)
        modes = set(case.get("modes") or [])
        _require(modes <= ALLOWED_MODES, f"{cid}: unknown modes {sorted(modes - ALLOWED_MODES)}", errors)
        _require(bool(case.get("script", {}).get("chief_complaint")), f"{cid}: script.chief_complaint required", errors)
        _require(case.get("evidence_status") == "catalog_only", f"{cid}: evidence_status must stay catalog_only until a run file is written", errors)
        for item in case.get("mapped_tests") or []:
            kind = item.get("kind")
            _require(kind in ALLOWED_TEST_KINDS, f"{cid}: unknown mapped test kind {kind!r}", errors)
            if kind == "pytest":
                nodeid = item.get("nodeid", "")
                rel = ROOT / item.get("cwd", "backend") / nodeid.split("::", 1)[0]
                _require(rel.is_file(), f"{cid}: mapped pytest file missing: {rel}", errors)
            elif kind == "e2e_script":
                rel = ROOT / item.get("cwd", "backend") / item.get("path", "")
                _require(rel.is_file(), f"{cid}: mapped e2e script missing: {rel}", errors)

        if cid == "SM-02":
            unknown = {item["id"] for item in case.get("unknown_facts") or []}
            _require("pmh_allergy" in unknown, "SM-02 must keep pmh_allergy unknown", errors)
            phrases = (case.get("unknown_facts") or [{}])[0].get("forbidden_phrases") or []
            _require("无过敏" in phrases, "SM-02 must forbid 无过敏", errors)

    return errors


def _empty_score() -> dict[str, Any]:
    return {
        field: {"first_token": None, "report": None} if field == "latency_ms"
        else {"prompt": None, "completion": None, "usd": None} if field == "token_cost"
        else None
        for field in SCORE_FIELDS
    }


def result_template(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_id": catalog["id"],
        "catalog_version": catalog["version"],
        "status": "not_run",
        "run_at": None,
        "environment": {
            "model": None,
            "prompt_version": None,
            "substitute_used": None,
            "database": None,
        },
        "summary": {
            "cases": len(catalog["cases"]),
            "engineering_pytest": "not_run",
            "live_model": "not_run",
            "human_review": "not_run",
        },
        "cases": [
            {
                "id": case["id"],
                "title": case["title"],
                "modes": case["modes"],
                "failure_stage": None,
                "notes": "",
                "scores": _empty_score(),
            }
            for case in catalog["cases"]
        ],
    }


def patient_fact_semantics_contract() -> list[str]:
    """DB-free checks for explicit unknown, denial, onset and conflicting answers."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.case_preparation import build_package

    errors: list[str] = []
    base = {
        "case": {
            "title": "合成评测病例",
            "chief_complaint": "吃完海鲜后皮肤发痒、起疹子。",
        },
        "report": {"primary_diagnosis": "辅助整理，非确诊"},
        "source_session_id": "synthetic-session",
        "materials": [],
        "patient_profile": {},
    }
    missing = build_package({**base, "patient_facts": {"hpi_onset": "昨晚晚饭后约一小时"}}, [])
    unknown_ids = {item["id"] for item in missing["unknown_facts"]}
    if "unknown.allergies" not in unknown_ids:
        errors.append("SM-02 contract: missing allergy key must yield unknown.allergies")

    known = build_package({**base, "patient_facts": {"pmh_allergy": "青霉素过敏，出现过皮疹"}}, [])
    known_unknown = {item["id"] for item in known["unknown_facts"]}
    if "unknown.allergies" in known_unknown:
        errors.append("SM-01 contract: stated penicillin allergy must not be marked unknown")

    unclear = build_package({**base, "patient_facts": {"pmh_allergy": "不清楚"}}, [])
    unclear_unknown = {item["id"] for item in unclear["unknown_facts"]}
    if "unknown.allergies" not in unclear_unknown:
        errors.append("SM-02 contract: pmh_allergy='不清楚' must stay unknown")
    if any(fact["id"] == "patient.reported.pmh_allergy" for fact in unclear["known_facts"]):
        errors.append("SM-02 contract: unclear allergy must not be listed as a known fact")

    denied = build_package({**base, "patient_facts": {"pmh_allergy": "明确无"}}, [])
    if "unknown.allergies" in {item["id"] for item in denied["unknown_facts"]}:
        errors.append("Explicit allergy denial must not be marked unknown")
    denial_fact = next(
        (fact for fact in denied["known_facts"] if fact["id"] == "patient.reported.pmh_allergy"),
        None,
    )
    if denial_fact is None or denial_fact.get("assertion_status") != "denied":
        errors.append("Explicit allergy denial must retain a distinct denied status")

    onset = build_package({**base, "patient_facts": {"hpi_onset": "不记得"}}, [])
    onset_fact = next(
        (fact for fact in onset["unknown_facts"] if fact["id"] == "unknown.hpi_onset"),
        None,
    )
    if onset_fact is None or onset_fact.get("patient_response") != "不记得":
        errors.append("SM-03 contract: unknown onset must preserve the patient response")

    conflict = build_package(
        {
            **base,
            "patient_facts": {"hpi_associated": "无发热"},
            "raw_answers": {"hpi_associated": "我没发过烧。"},
            "raw_answer_history": {"hpi_associated": ["测到 38.5℃。", "我没发过烧。"]},
        },
        [],
    )
    unresolved = next(
        (fact for fact in conflict["unresolved_facts"] if fact["id"] == "unresolved.hpi_associated"),
        None,
    )
    if unresolved is None or [item["value"] for item in unresolved["statements"]] != [
        "测到 38.5℃。", "我没发过烧。"
    ]:
        errors.append("SM-04 contract: both conflicting patient statements must remain unresolved")
    if any(fact["id"] == "patient.reported.hpi_associated" for fact in conflict["known_facts"]):
        errors.append("SM-04 contract: latest structured value must not silently win over history")
    return errors


def mapped_pytest_nodeids(catalog: dict[str, Any]) -> list[str]:
    nodeids: list[str] = []
    for case in catalog["cases"]:
        for item in case.get("mapped_tests") or []:
            if item.get("kind") == "pytest":
                nodeids.append(item["nodeid"])
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(nodeids))


def run_mapped_pytest(catalog: dict[str, Any]) -> int:
    nodeids = mapped_pytest_nodeids(catalog)
    if not nodeids:
        print("No mapped pytest nodeids")
        return 0
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", *nodeids]
    print("Running:", " ".join(cmd))
    print("NOTE: many mapped tests need PostgreSQL via TEST_DATABASE_URL; SQLite JSONB setup errors are not case passes.")
    completed = subprocess.run(cmd, cwd=ROOT / "backend")
    return completed.returncode


def write_template(catalog: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(result_template(catalog), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_table(catalog: dict[str, Any]) -> None:
    print(f"{'ID':<7}{'family':<18}{'modes':<42}pytest  title")
    for case in catalog["cases"]:
        pytest_n = sum(1 for item in case["mapped_tests"] if item.get("kind") == "pytest")
        modes = ",".join(case["modes"])
        print(f"{case['id']:<7}{case['family']:<18}{modes:<42}{pytest_n:<7}{case['title']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate catalog and preparation contracts")
    parser.add_argument("--pytest", action="store_true", help="run mapped engineering pytest nodeids")
    parser.add_argument("--write-template", nargs="?", const=str(TEMPLATE_PATH), help="write an empty results file")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)

    if not (args.check or args.pytest or args.write_template):
        args.check = True

    catalog = load_catalog(args.catalog)
    errors = validate_catalog(catalog)
    errors.extend(patient_fact_semantics_contract())
    print_table(catalog)
    print(f"status={catalog['status']} cases={len(catalog['cases'])} split={catalog['split']}")
    if errors:
        print("CATALOG INVALID")
        for item in errors:
            print(f"- {item}")
        return 1
    print("CATALOG OK (defined, not run)")

    if args.write_template:
        target = Path(args.write_template)
        write_template(catalog, target)
        print(f"wrote {target}")

    if args.pytest:
        return run_mapped_pytest(catalog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
