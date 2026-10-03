"""真实 SDK 组件实测；未运行 NER/NLI/brief 不进入成绩汇总。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import socket
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import run_eval
import sdk_adapter

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1] / ".ai/tasks/2026-09-30-openmed-transfer"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OPENMED_OFFLINE",
                 "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[name] = "1"
    os.environ["HF_HOME"] = str(TASK / "hf-cache")
    os.environ["XDG_CACHE_HOME"] = str(TASK / "runtime-cache")
    network_attempts = []

    def forbid_connect(sock, address):
        network_attempts.append(str(address))
        raise RuntimeError("离线实验禁止网络连接")

    socket.socket.connect = forbid_connect
    socket.socket.connect_ex = forbid_connect
    catalog = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
    errors = run_eval.validate_catalog(catalog)
    if errors:
        raise ValueError(errors)
    cases = catalog["cases"]
    if args.smoke:
        cases = [c for c in cases if c["id"] in {"D01", "D03", "D08", "E07", "E09"}]
    funcs = run_eval.load_baseline()
    manifest = None
    model_path = TASK / "openmed-zh-model"
    config = loader = None
    load_ms = None
    if not args.context_only:
        manifest = json.loads((TASK / "openmed-model-manifest.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = model_path / item["name"]
            if path.stat().st_size != item["size"] or sha(path) != item["sha256"]:
                raise ValueError(f"模型校验失败：{item['name']}")
        from openmed import ModelLoader, OpenMedConfig
        config = OpenMedConfig(device="cpu", backend="hf", local_only=True,
                               cache_dir=str(TASK / "sdk-cache"), num_workers=0,
                               chinese_segmentation_backend="jieba")
        loader = ModelLoader(config)
        start = time.perf_counter()
        loader.create_pipeline(str(model_path), aggregation_strategy="simple")
        load_ms = (time.perf_counter() - start) * 1000
        print(f"MODEL LOADED {load_ms:.0f} ms", flush=True)
    rows = []
    for case in cases:
        inp = case["input"]
        # 仅为复用既有评分契约提供业务包；这些字段不作为 SDK 测量项。
        output = run_eval.baseline_process(inp, funcs)
        start = time.perf_counter()
        output["assertions"], raw_context = sdk_adapter.context_assertions(inp)
        context_ms = (time.perf_counter() - start) * 1000
        pii_ms = None
        if not args.context_only:
            start = time.perf_counter()
            output.update(sdk_adapter.extract_and_mask(inp["text"], str(model_path), config, loader))
            pii_ms = (time.perf_counter() - start) * 1000
        scored = run_eval.score(case, output)
        if scored["contract_errors"]:
            raise ValueError((case["id"], scored["contract_errors"]))
        measured = {"assertions": scored["assertions"],
                    "privacy": None if args.context_only else scored["privacy"],
                    "protected": None if args.context_only else scored["protected"]}
        row = {"id": case["id"], "split": case["split"], "score": measured,
               "raw_context": raw_context, "context_ms": context_ms, "pii_ms": pii_ms,
               "redactions": None if args.context_only else output["redactions"],
               "redacted_text": None if args.context_only else output["redacted_text"]}
        rows.append(row)
        print(f"CASE {case['id']} context={context_ms:.1f}ms pii={pii_ms}", flush=True)
    summaries = {}
    for split in ("all", "development", "evaluation"):
        selected = [r for r in rows if split == "all" or r["split"] == split]
        assertions = [a for r in selected for a in r["score"]["assertions"]]
        total, correct = len(assertions), sum(a["correct"] for a in assertions)
        summaries[split] = {"case_count": len(selected), "assertions": {
            "total": total, "correct": correct, "accuracy": correct / total if total else None,
            "false_present": sum(a["actual"] == "present" and a["expected"] != "present" for a in assertions),
            "false_refuted": sum(a["actual"] == "refuted" and a["expected"] != "refuted" for a in assertions)},
            "privacy": None, "protected": None, "pii_median_ms": None}
        if not args.context_only:
            privacy = {k: sum(r["score"]["privacy"][k] for r in selected)
                       for k in selected[0]["score"]["privacy"]}
            privacy["recall"] = privacy["detected_gold_chars"] / privacy["gold_chars"] if privacy["gold_chars"] else None
            privacy["precision"] = privacy["detected_gold_chars"] / privacy["redacted_chars"] if privacy["redacted_chars"] else None
            summaries[split]["privacy"] = privacy
            summaries[split]["protected"] = {
                k: sum(r["score"]["protected"][k] for r in selected) for k in ("total", "preserved")}
            summaries[split]["pii_median_ms"] = statistics.median(r["pii_ms"] for r in selected)
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "mode": "smoke" if args.smoke else "full", "synthetic": True,
              "not_blind": True, "decision": "HOLD_NO_PRODUCTION_INTEGRATION",
              "components": {"context": "MEASURED_SDK_RULES",
                             "pii": "NOT_RUN" if args.context_only else "MEASURED_SDK_EXTRACT_PLUS_STAR_ADAPTER",
                             "ner": "NOT_RUN", "nli": "NOT_RUN", "brief": "NOT_RUN",
                             "medaxis_history": "NOT_MEASURED_AS_SDK"},
              "versions": {name: importlib.metadata.version(name) for name in
                           ("openmed", "transformers", "huggingface-hub", "torch", "pydantic")},
              "source_sha256": {name: sha(HERE / name) for name in
                                ("catalog.json", "sdk_adapter.py", "run_sdk_eval.py", "run_eval.py")},
              "model": manifest, "threshold": 0.5, "lang": "zh", "device": "cpu",
              "load_ms": load_ms, "network_attempts": network_attempts,
              "summaries": summaries, "cases": rows}
    if network_attempts:
        raise RuntimeError("SDK 曾尝试网络访问；不发布成功报告")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries["all"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
