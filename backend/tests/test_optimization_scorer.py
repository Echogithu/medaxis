"""评分器对错例和缺失数据都必须能证伪，防止运行成功冒充效果。"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("optimization_score", Path(__file__).resolve().parents[2] / "evals/consultation-optimization/score.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_评分器拒绝少题但误结束及缺失数据():
    expected = {"question_ids": [], "sufficient": False, "action": "ask"}
    assert module.score_case(expected, expected)["passed"]
    assert not module.score_case(expected, {**expected, "sufficient": True})["passed"]
    assert not module.score_case(expected, {**expected, "action": "synthesize"})["passed"]
    assert not module.score_case(expected, {})["passed"]


def test_评分器拒绝丢失未知及遗漏来源顺序():
    assert not module.score_case({"summary_contains": "不清楚"}, {"summary": "明确无"})["passed"]
    assert not module.score_case({"source_keys": ["external", "internal"]}, {"source_keys": ["internal", "external"]})["passed"]


def test_真实汇总拒绝空数据及缺失场景():
    for rows in [[], [{"id": "profile_reuse", "error": False, "calls": [], "question_count": 0, "recorded_dimension_reasks": 0, "elapsed_ms": 1}]]:
        data = module.summarize_live_record({"cases": rows}, {"profile_reuse", "unknown_reuse", "chief_reuse"})
        assert data["questions"] is None
        assert data["total_tokens"] is None
        assert not data["complete_dataset"]
