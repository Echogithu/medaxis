"""中文合成迁移对照：真实业务函数基线与离线规则原型，不调用模型/数据库。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import statistics
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import candidate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CATALOG = HERE / "catalog.json"
BASELINE_FILES = (
    "backend/app/models/patient_answer.py",
    "backend/app/services/case_preparation.py",
    "backend/app/services/department_guidance.py",
    "backend/app/services/knowledge_citations.py",
)


def load_baseline():
    """跳过 ORM 包初始化，运行真实函数；不读取 .env，也不伪造函数输出。"""
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    models_package = types.ModuleType("app.models")
    models_package.__path__ = [str(ROOT / "backend/app/models")]
    with patch.dict(sys.modules, {"app.models": models_package}):
        spec = importlib.util.spec_from_file_location(
            "preparation_baseline", ROOT / "backend/app/services/case_preparation.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from app.services.knowledge_citations import (
            attach_knowledge_citations, build_knowledge_citations,
        )
    return module.build_package, build_knowledge_citations, attach_knowledge_citations


def valid_span(span: dict, text: str) -> bool:
    return (isinstance(span, dict) and type(span.get("start")) is int
            and type(span.get("end")) is int
            and 0 <= span["start"] < span["end"] <= len(text))


def validate_catalog(catalog: dict) -> list[str]:
    errors = []
    if catalog.get("synthetic") is not True or catalog.get("version") != "1.0.0":
        errors.append("catalog 必须明确 synthetic=true 和版本")
    cases = catalog.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["cases 必须是非空数组"]
    seen = set()
    for case in cases:
        cid = case.get("id")
        if not isinstance(cid, str) or not cid or cid in seen:
            errors.append(f"重复或无效 case id: {cid}")
        seen.add(cid)
        if case.get("split") not in {"development", "evaluation"}:
            errors.append(f"{cid}: split 无效")
        inp, gold = case.get("input", {}), case.get("gold", {})
        text = inp.get("text")
        if not isinstance(text, str) or not text or not inp.get("field"):
            errors.append(f"{cid}: 缺少 text/field")
            continue
        mentions = inp.get("mentions", [])
        assertions = gold.get("assertions", [])
        positions = [(m.get("start"), m.get("end")) for m in mentions]
        if len(set(positions)) != len(positions):
            errors.append(f"{cid}: 重复提及")
        if positions != [(m.get("start"), m.get("end")) for m in assertions]:
            errors.append(f"{cid}: assertion gold 与提及位置不一致")
        for item in [*mentions, *assertions, *gold.get("pii", []), *gold.get("protected", [])]:
            if not valid_span(item, text) or text[item["start"]:item["end"]] != item.get("text"):
                errors.append(f"{cid}: 原文 span 无效")
        for item in assertions:
            if item.get("status") not in candidate.STATUSES:
                errors.append(f"{cid}: assertion status 无效")
        pii_positions = {i for span in gold.get("pii", [])
                         if valid_span(span, text) for i in range(span["start"], span["end"])}
        if any(pii_positions.intersection(range(span["start"], span["end"]))
               for span in gold.get("protected", []) if valid_span(span, text)):
            errors.append(f"{cid}: 隐私与受保护信息重叠")
        claims = inp.get("claims", [])
        if [c.get("id") for c in claims] != [c.get("id") for c in gold.get("claims", [])]:
            errors.append(f"{cid}: claim gold 与输入不一致")
        if len({c.get("id") for c in claims}) != len(claims):
            errors.append(f"{cid}: 重复 claim id")
        if any(type(c.get("supported")) is not bool for c in gold.get("claims", [])):
            errors.append(f"{cid}: supported 必须是布尔值")
        for claim in claims:
            if (not isinstance(claim.get("text"), str) or not claim["text"]
                    or not isinstance(claim.get("citation_id"), str)
                    or type(claim.get("evidence_start")) is not int
                    or type(claim.get("evidence_end")) is not int):
                errors.append(f"{cid}: claim 输入无效")
    return errors


def baseline_process(inp: dict, funcs: tuple) -> dict:
    build_package, build_citations, attach_citations = funcs
    key, text = inp["field"], inp["text"]
    history = inp.get("history", [text])
    source = {
        "case": {"title": "合成迁移评测", "chief_complaint": "合成资料整理"},
        "patient_facts": {key: inp.get("value", text)},
        "raw_answers": {key: history[-1]}, "raw_answer_history": {key: history},
        "patient_profile": {}, "report": None, "materials": [],
        "source_session_id": "synthetic-transfer-session",
    }
    package = build_package(source, [])
    unresolved = any(f["id"] == f"unresolved.{key}" for f in package["unresolved_facts"])
    fact = next((f for f in package["known_facts"] if f["id"] == f"patient.reported.{key}"), None)
    unknown = any(f.get("source_id") == f"source_session.interview.collected_info.{key}"
                  for f in package["unknown_facts"])
    status = "needs_review"
    if not unresolved:
        if unknown:
            status = "unknown"
        elif fact:
            status = {"denied": "refuted", "affirmed": "present"}.get(
                fact.get("assertion_status"), "needs_review",
            )
    citations = build_citations(inp["sources"])
    claims = []
    for claim in inp["claims"]:
        report = attach_citations(
            {"finding": claim["text"] + f" [{claim['citation_id']}]"}, citations,
        )
        admitted = any(c["citation_id"] == claim["citation_id"]
                       for c in report["knowledge_citations"])
        claims.append({"id": claim["id"], "verdict": "accepted" if admitted else "rejected"})
    return {
        "package": package, "redacted_text": text, "redactions": [],
        "assertions": [{"start": m["start"], "end": m["end"], "status": status}
                       for m in inp["mentions"]],
        "claims": claims, "citations": [c.model_dump() for c in citations],
    }


def score(case: dict, output: dict) -> dict:
    """只读取独立 gold 评分；缺失/越界/重复结果显式失败。"""
    inp, gold = case["input"], case["gold"]
    text = inp["text"]
    errors = []
    redacted = output.get("redacted_text")
    if not isinstance(redacted, str) or len(redacted) != len(text):
        errors.append("缺失或非等长 redacted_text")
        redacted = text
    detections = output.get("redactions")
    if not isinstance(detections, list):
        errors.append("缺失 redactions")
        detections = []
    if any(not valid_span(span, text) for span in detections):
        errors.append("脱敏位置无效")
    marked = {i for span in detections if valid_span(span, text)
              for i in range(span["start"], span["end"])}
    changed = {i for i, (old, new) in enumerate(zip(text, redacted)) if old != new}
    if marked != changed:
        errors.append("标记位置与实际遮蔽不一致")
    masked = {i for i in changed if redacted[i] == "*"}
    if masked != changed:
        errors.append("本实验只接纳星号遮蔽，不把同长度替换值当作去标识")
    pii = {i for span in gold["pii"] for i in range(span["start"], span["end"])}
    protected = gold["protected"]
    assertions = output.get("assertions")
    if not isinstance(assertions, list):
        errors.append("缺失 assertions")
        assertions = []
    expected_positions = {(m["start"], m["end"]) for m in inp["mentions"]}
    actual_positions = [(a.get("start"), a.get("end")) for a in assertions]
    if len(set(actual_positions)) != len(actual_positions) or set(actual_positions) != expected_positions:
        errors.append("提及结果缺失、重复或多余")
    by_position = {(a.get("start"), a.get("end")): a for a in assertions}
    if any(a.get("status") not in candidate.STATUSES for a in assertions):
        errors.append("未知 assertion 输出状态")
    assertion_rows = []
    for item in gold["assertions"]:
        actual = by_position.get((item["start"], item["end"]), {}).get("status", "missing")
        assertion_rows.append({"text": item["text"], "expected": item["status"],
                               "actual": actual, "correct": actual == item["status"]})
    claim_outputs = output.get("claims")
    if not isinstance(claim_outputs, list):
        errors.append("缺失 claims")
        claim_outputs = []
    ids = [c.get("id") for c in claim_outputs]
    if len(set(ids)) != len(ids) or set(ids) != {c["id"] for c in inp["claims"]}:
        errors.append("claim 结果缺失、重复或多余")
    if any(c.get("verdict") not in {"accepted", "rejected", "review"} for c in claim_outputs):
        errors.append("未知 claim verdict")
    claims_by_id = {c.get("id"): c for c in claim_outputs}
    claim_rows = [{"id": c["id"], "supported": c["supported"],
                   "verdict": claims_by_id.get(c["id"], {}).get("verdict", "missing")}
                  for c in gold["claims"]]
    package = output.get("package")
    preserved = False
    package_ok = isinstance(package, dict) and all(
        isinstance(package.get(key), list)
        and all(isinstance(item, dict) and isinstance(item.get("id"), str)
                for item in package[key])
        for key in ("known_facts", "unknown_facts", "unresolved_facts")
    )
    if package_ok:
        package_ok = all(
            isinstance(f.get("statements"), list)
            and all(isinstance(s, dict) and isinstance(s.get("value"), str)
                    for s in f["statements"])
            for f in package["unresolved_facts"]
        )
    if package_ok:
        facts = package["known_facts"] + package["unknown_facts"]
        history = inp.get("history", [text])
        if len(set(history)) > 1:
            preserved = any([s["value"] for s in f["statements"]] == history
                            for f in package.get("unresolved_facts", [])
                            if f.get("id") == f"unresolved.{inp['field']}")
        else:
            preserved = any(f.get("patient_response_history") == history for f in facts)
    else:
        errors.append("缺失或无效 package 事实数组")
    return {
        "contract_errors": errors,
        "privacy": {"gold_chars": len(pii), "detected_gold_chars": len(pii & masked),
                    "false_redacted_chars": len(masked - pii), "redacted_chars": len(masked),
                    "leaked_chars": len(pii - masked)},
        "protected": {"total": len(protected), "preserved": sum(
            redacted[s["start"]:s["end"]] == s["text"] for s in protected)},
        "assertions": assertion_rows, "claims": claim_rows, "raw_history_preserved": preserved,
    }


def ratio(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def summarize(rows: list[dict], adapter: str) -> dict:
    scores = [r[adapter]["score"] for r in rows]
    privacy = {key: sum(s["privacy"][key] for s in scores) for key in scores[0]["privacy"]}
    assertions = [a for s in scores for a in s["assertions"]]
    claims = [c for s in scores for c in s["claims"]]
    correct = sum(a["correct"] for a in assertions)
    unsupported = [c for c in claims if not c["supported"]]
    supported = [c for c in claims if c["supported"]]
    accepted = [c for c in claims if c["verdict"] == "accepted"]
    latencies = [r[adapter]["latency_ms"] for r in rows]
    return {
        "cases": len(rows), "contract_errors": sum(len(s["contract_errors"]) for s in scores),
        "privacy": {**privacy, "character_recall": ratio(privacy["detected_gold_chars"], privacy["gold_chars"]),
                    "character_precision": ratio(privacy["detected_gold_chars"], privacy["redacted_chars"])},
        "protected_preserved": sum(s["protected"]["preserved"] for s in scores),
        "protected_total": sum(s["protected"]["total"] for s in scores),
        "assertions_correct": correct, "assertions_total": len(assertions),
        "assertion_accuracy": ratio(correct, len(assertions)),
        "assertion_needs_review": sum(a["actual"] == "needs_review" for a in assertions),
        "unsafe_present": sum(a["actual"] == "present" and a["expected"] != "present" for a in assertions),
        "incorrect_refuted": sum(a["actual"] == "refuted" and a["expected"] != "refuted" for a in assertions),
        "raw_history_preserved": sum(s["raw_history_preserved"] for s in scores),
        "claims_total": len(claims), "supported_claims": len(supported),
        "supported_accepted": sum(c["verdict"] == "accepted" for c in supported),
        "unsupported_claims": len(unsupported),
        "unsupported_accepted": sum(c["verdict"] == "accepted" for c in unsupported),
        "accepted_support_precision": ratio(sum(c["supported"] for c in accepted), len(accepted)),
        "supported_admission_recall": ratio(sum(c["verdict"] == "accepted" for c in supported), len(supported)),
        "claims_review": sum(c["verdict"] == "review" for c in claims),
        "latency_ms_median": round(statistics.median(latencies), 4),
        "latency_scope": "单次本地函数调用；基线先调用，候选复用基线包；不是服务性能比较",
    }


def run(catalog: dict, smoke: bool = False) -> dict:
    funcs = load_baseline()
    smoke_ids = {"D01", "D03", "D06", "D07", "D08"}
    cases = [c for c in catalog["cases"] if c["id"] in smoke_ids] if smoke else catalog["cases"]
    rows = []
    for case in cases:
        inp = copy.deepcopy(case["input"])
        start = time.perf_counter_ns()
        base = baseline_process(inp, funcs)
        base_ms = (time.perf_counter_ns() - start) / 1_000_000
        start = time.perf_counter_ns()
        proposed = candidate.process(copy.deepcopy(inp), copy.deepcopy(base))
        candidate_ms = (time.perf_counter_ns() - start) / 1_000_000
        rows.append({"id": case["id"], "split": case["split"],
                     "baseline": {"output": base, "score": score(case, base), "latency_ms": base_ms},
                     "candidate": {"output": proposed, "score": score(case, proposed), "latency_ms": candidate_ms}})
    groups = {"all": rows}
    groups.update({split: [r for r in rows if r["split"] == split]
                   for split in ("development", "evaluation")})
    return {
        "run_at": datetime.now(timezone.utc).isoformat(), "mode": "offline_synthetic_rules",
        "smoke": smoke,
        "openmed_sdk_executed": False, "model_executed": False, "database_used": False,
        "candidate_version": candidate.VERSION, "python": sys.version.split()[0],
        "catalog_sha256": hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                          for path in (*BASELINE_FILES, "evals/openmed-transfer/candidate.py", "evals/openmed-transfer/run_eval.py")},
        "summary": {name: {adapter: summarize(group, adapter) for adapter in ("baseline", "candidate")}
                    for name, group in groups.items() if group}, "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    errors = validate_catalog(catalog)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"CATALOG OK: {len(catalog['cases'])} 个固定合成案例")
    if args.check:
        return 0
    report = run(catalog, smoke=args.smoke)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"结果：{args.output}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    # 质量失败保留在成绩单；只对执行/输出契约失败返回非零。
    return int(any(row[adapter]["score"]["contract_errors"]
                   for row in report["cases"] for adapter in ("baseline", "candidate")))


if __name__ == "__main__":
    raise SystemExit(main())
