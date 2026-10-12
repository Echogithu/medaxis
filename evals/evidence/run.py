"""复用固定回归入口，冻结输入与源码，保存逐题证据并拒绝不可比较的收益。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "evals/consultation-optimization"
MODE = "fixed_response_control"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scorer(path):
    spec = importlib.util.spec_from_file_location("frozen_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_case


def grade(catalog, raw, score):
    cases, rows = catalog.get("cases"), raw.get("cases")
    if not isinstance(cases, list) or not cases or not isinstance(rows, list):
        raise ValueError("空题集或缺少逐题结果，不能评分")
    if any(not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"] for c in cases + rows):
        raise ValueError("题目/结果必须是对象，并包含非空字符串 ID")
    ids = [c["id"] for c in cases]
    observed = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids) or len(set(observed)) != len(observed):
        raise ValueError("题目或结果存在重复 ID")
    if set(ids) != set(observed):
        raise ValueError(f"结果不完整：缺失={sorted(set(ids)-set(observed))}；多余={sorted(set(observed)-set(ids))}")
    by_id = {row["id"]: row for row in rows}
    result = []
    for case in cases:
        if not case.get("expected"):
            raise ValueError(f"{case['id']} 缺少判定标准")
        row = by_id[case["id"]]
        if type(row.get("error")) is not bool:
            raise ValueError(f"{case['id']} 缺少显式执行状态")
        result.append({"id": case["id"], "kind": case["kind"], **score(case["expected"], row)})
    return result


def validate_record(path):
    path = Path(path)
    record = load(path)
    if record.get("mode") != MODE or record.get("status") != "complete":
        raise ValueError("记录不是完整固定响应回归；不能混入真实模型或未执行结果")
    hashes = record.get("artifact_sha256", {})
    for name in ("dataset.json", "raw.json", "score.py", "probe.py", "runner.py"):
        if hashes.get(name) != sha(path.parent / name):
            raise ValueError(f"证据文件指纹不符：{name}")
    if record.get("conditions", {}).get("dependencies_sha256") != sha(path.parent / "dependencies.json"):
        raise ValueError("依赖证据指纹不符")
    source_hashes = record.get("source_sha256", {})
    if not source_hashes:
        raise ValueError("缺少源码快照指纹")
    for name, digest in source_hashes.items():
        target = (path.parent / "source" / name).resolve()
        if not target.is_relative_to((path.parent / "source").resolve()) or digest != sha(target):
            raise ValueError(f"源码快照指纹不符：{name}")
    current = grade(load(path.parent / "dataset.json"), load(path.parent / "raw.json"), scorer(path.parent / "score.py"))
    if record.get("cases") != current or record.get("passed") != sum(r["passed"] for r in current) or record.get("total") != len(current):
        raise ValueError("成绩与原始结果不一致")
    return record


def compare_records(before, after):
    for field in ("mode", "conditions"):
        if before[field] != after[field]:
            raise ValueError(f"不可比较：{field} 改变")
    for name in ("dataset.json", "score.py", "probe.py", "runner.py"):
        if before["artifact_sha256"][name] != after["artifact_sha256"][name]:
            raise ValueError(f"不可比较：{name} 改变")
    left = {r["id"]: r for r in before["cases"]}
    right = {r["id"]: r for r in after["cases"]}
    if not left or set(left) != set(right):
        raise ValueError("不可比较：题目缺失")
    improved = [cid for cid in left if not left[cid]["passed"] and right[cid]["passed"]]
    regressed = [cid for cid in left if left[cid]["passed"] and not right[cid]["passed"]]
    verdict = "regression" if regressed else "improved_on_this_control_set" if improved else "no_quality_gain"
    return {"verdict": verdict, "total": len(left), "before_passed": before["passed"],
            "after_passed": after["passed"], "delta_percentage_points": round(100*(after["passed"]-before["passed"])/len(left), 2),
            "improved_ids": improved, "regressed_ids": regressed,
            "still_failing_ids": [cid for cid in right if not right[cid]["passed"]],
            "changed_source_files": sorted(k for k in set(before["source_sha256"]) | set(after["source_sha256"])
                                           if before["source_sha256"].get(k) != after["source_sha256"].get(k)),
            "scope": "只证明该固定回归集上的约束变化；不是医学、真实检索质量、Token或生产性能收益"}


def run(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    backend = args.backend.resolve()
    catalog = load(CONTROL / "catalog.json")
    if args.ids:
        wanted = set(args.ids.split(","))
        if not wanted <= {c["id"] for c in catalog["cases"]}:
            raise ValueError("指定了不存在的题目")
        catalog["cases"] = [c for c in catalog["cases"] if c["id"] in wanted]
    write_json(out / "dataset.json", catalog)
    for name in ("score.py", "probe.py"):
        shutil.copyfile(CONTROL / name, out / name)
    shutil.copyfile(Path(__file__), out / "runner.py")
    hashes = {}
    for source in sorted((backend / "app").rglob("*.py")):
        relative = source.relative_to(backend)
        target = out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = sha(target)
    if not hashes:
        raise ValueError("没有找到后端源码")
    command = [sys.executable, str(out / "probe.py"), "--source-root", str(out / "source"),
               "--catalog", str(out / "dataset.json"), "--output", str(out / "raw.json")]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "SECRET_KEY": "synthetic-evaluation-not-a-secret",
           "DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_import_only",
           "ASYNC_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_import_only"}
    process = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    (out / "execution.log").write_text(process.stdout + process.stderr, encoding="utf-8")
    write_json(out / "execution.json", {"command": command, "exit_code": process.returncode})
    if process.returncode:
        raise ValueError(f"执行失败 exit={process.returncode}，保留日志，不生成成功成绩单")
    cases = grade(catalog, load(out / "raw.json"), scorer(out / "score.py"))
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    packages = sorted((d.metadata.get("Name", ""), d.version) for d in importlib.metadata.distributions())
    write_json(out / "dependencies.json", packages)
    record = {"created_at": datetime.now(timezone.utc).isoformat(), "mode": MODE, "status": "complete",
              "label": args.label, "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
              "conditions": {"model": "fixed-fixture", "database": "blocked", "external_search": "fixture",
                             "clinical_gold": "not_reviewed", "python": sys.version.split()[0],
                             "dependencies_sha256": sha(out / "dependencies.json")},
              "artifact_sha256": {n: sha(out / n) for n in ("dataset.json", "raw.json", "score.py", "probe.py", "runner.py")},
              "source_sha256": hashes, "cases": cases, "passed": sum(r["passed"] for r in cases), "total": len(cases),
              "usage": {"input_tokens": None, "output_tokens": None, "cost": None},
              "scope": "合成固定响应的问诊/来源控制层回归；真实模型、真实检索与临床正确性未评估"}
    write_json(out / "record.json", record)
    validate_record(out / "record.json")
    print(f"{args.label}: {record['passed']}/{record['total']}；证据 {out / 'record.json'}")
    return 0 if record["passed"] == record["total"] else 1


def compare(args):
    before, after = validate_record(args.before), validate_record(args.after)
    result = compare_records(before, after)
    result.update(hypothesis=args.hypothesis, change=args.change, before=str(args.before.resolve()), after=str(args.after.resolve()))
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "comparison.json", result)
    rows = ["# 优化对比记录", "", f"假设：{args.hypothesis}", f"改动：{args.change}", "",
            f"结论：**{result['verdict']}**", f"改前 {before['passed']}/{before['total']}；改后 {after['passed']}/{after['total']}；变化 {result['delta_percentage_points']} 个百分点。",
            f"改善：{result['improved_ids']}；退步：{result['regressed_ids']}；仍失败：{result['still_failing_ids']}", "", result["scope"], "",
            "| 题目 | 改前 | 改后 | 改后失败约束 |", "|---|---|---|---|"]
    left = {r["id"]: r for r in before["cases"]}
    for row in after["cases"]:
        rows.append(f"| {row['id']} | {left[row['id']]['passed']} | {row['passed']} | {', '.join(row['failed_constraints'])} |")
    rows += ["", f"改前原始记录：{result['before']}", f"改后原始记录：{result['after']}"]
    (args.output / "REPORT.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"{result['verdict']}；改善 {len(result['improved_ids'])}；退步 {len(result['regressed_ids'])}")
    return 1 if result["regressed_ids"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", type=Path, default=ROOT / "backend")
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--label", required=True)
    r.add_argument("--ids", help="仅用于冒烟；不同子集不允许前后比较")
    c = sub.add_parser("compare")
    c.add_argument("--before", type=Path, required=True)
    c.add_argument("--after", type=Path, required=True)
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--hypothesis", required=True)
    c.add_argument("--change", required=True)
    args = parser.parse_args()
    try:
        return run(args) if args.action == "run" else compare(args)
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"评估未通过：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
