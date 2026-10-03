"""只汇总完整真实调用；失败或缺失用量不能被当成零题或省 Token。"""
import argparse
import json
from pathlib import Path
from score import summarize_live_record


parser = argparse.ArgumentParser()
parser.add_argument("--before", type=Path, required=True)
parser.add_argument("--after", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
expected_ids = {row["id"] for row in json.loads((Path(__file__).parent / "live-fixtures.json").read_text(encoding="utf-8"))["cases"]}
result = {"scope": "3 个合成场景各一次真实模型调用对比；不是统计显著性或医学效果评估"}
for label, path in [("before", args.before), ("after", args.after)]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    result[label] = summarize_live_record(data, expected_ids)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(result[label]["complete_dataset"] and result[label]["successful_cases"] == len(expected_ids)
                         for label in ["before", "after"]) else 1)
