"""仅比较可观察约束，不把模型完成、题目减少或空结果直接计为质量提升。"""
def score_case(expected, actual):
    failures = []
    for key, wanted in expected.items():
        if key == "summary_contains":
            passed = wanted in actual.get("summary", "")
        elif key == "gap_contains":
            passed = any(wanted in gap for gap in actual.get("gaps", []))
        else:
            passed = key in actual and wanted == actual[key]
        if not passed:
            failures.append(key)
    return {"passed": not failures, "failed_constraints": failures}


def summarize_live_record(data, expected_ids):
    """有遗漏、重复、失败或缺失用量时不生成完整收益指标。"""
    rows = data.get("cases", [])
    calls = [call for row in rows for call in row["calls"]]
    observed_ids = [row.get("id") for row in rows]
    complete_dataset = (len(rows) == len(expected_ids) and set(observed_ids) == expected_ids
                        and len(set(observed_ids)) == len(observed_ids))
    complete = complete_dataset and all(row.get("error") is False for row in rows)

    def total(field):
        return (sum(call[field] for call in calls)
                if complete and calls and all(isinstance(call.get(field), (int, float)) for call in calls) else None)

    result = {"total_cases": len(expected_ids), "observed_cases": len(rows), "complete_dataset": complete_dataset,
              "missing_ids": sorted(expected_ids - set(observed_ids)),
              "successful_cases": sum(row.get("error") is False and row.get("id") in expected_ids for row in rows),
              "model_calls": len(calls), "models": sorted({c.get("model", "unavailable") for c in calls}),
              "questions": sum(row["question_count"] for row in rows) if complete else None,
              "recorded_dimension_reasks": sum(row["recorded_dimension_reasks"] for row in rows) if complete else None,
              "prompt_tokens": total("prompt_tokens"), "completion_tokens": total("completion_tokens"),
              "total_elapsed_ms": round(sum(row["elapsed_ms"] for row in rows), 1) if complete else None}
    result["total_tokens"] = (result["prompt_tokens"] + result["completion_tokens"]
                              if result["prompt_tokens"] is not None and result["completion_tokens"] is not None else None)
    return result
