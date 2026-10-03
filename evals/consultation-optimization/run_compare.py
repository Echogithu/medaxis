"""修改前真实源码与当前源码同输入重放；每次运行写独立证据目录，不覆盖旧结果。"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from score import score_case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    catalog_path = here / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    data = {}
    for label, root in [("before", args.baseline), ("after", args.current)]:
        root = root.resolve()
        output = args.output.resolve() / f"{label}.json"
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
               "SECRET_KEY": "synthetic-evaluation-not-a-secret",
               "DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic_import_only"}
        completed = subprocess.run([sys.executable, str(here / "probe.py"), "--source-root", str(root),
                                    "--catalog", str(catalog_path), "--output", str(output)],
                                   cwd=here, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
        (args.output / f"{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(f"{label} 重放失败，见日志；退出码 {completed.returncode}")
        raw = json.loads(output.read_text(encoding="utf-8"))
        rows = {row["id"]: row for row in raw["cases"]}
        data[label] = {"passed": 0, "total": len(catalog["cases"]), "cases": []}
        for case in catalog["cases"]:
            verdict = score_case(case["expected"], rows.get(case["id"], {}))
            data[label]["passed"] += int(verdict["passed"])
            data[label]["cases"].append({"id": case["id"], **verdict})
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
              "scope": "固定模型响应的合成控制层测试；不衡量医学充分性、真实模型耗时或临床效果", **data}
    (args.output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"before {data['before']['passed']}/{data['before']['total']}；after {data['after']['passed']}/{data['after']['total']}")
    return 0 if data["after"]["passed"] == data["after"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
