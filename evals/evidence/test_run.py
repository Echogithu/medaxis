"""量尺必须区分正确、错误、遗漏、篡改和不可比较；不加载应用或数据库。"""
import copy
import tempfile
import unittest
from pathlib import Path

import run


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"cases": [{"id": "a", "kind": "interview", "expected": {"action": "ask"}},
                                  {"id": "b", "kind": "interview", "expected": {"error": True}}]}
        self.raw = {"cases": [{"id": "a", "error": False, "action": "ask"}, {"id": "b", "error": True}]}
        self.score = run.scorer(run.CONTROL / "score.py")

    def record(self, passed):
        cases = run.grade(self.catalog, self.raw, self.score)
        for row, value in zip(cases, passed):
            row["passed"] = value
        return {"mode": run.MODE, "conditions": {"model": "fixture"}, "cases": cases,
                "passed": sum(passed), "source_sha256": {"app/a.py": "same"},
                "artifact_sha256": {n: "same" for n in ("dataset.json", "score.py", "probe.py", "runner.py")}}

    def test_correct_wrong_and_expected_failure(self):
        self.assertTrue(all(r["passed"] for r in run.grade(self.catalog, self.raw, self.score)))
        self.raw["cases"][0]["action"] = "synthesize"
        self.assertFalse(run.grade(self.catalog, self.raw, self.score)[0]["passed"])

    def test_empty_missing_duplicate_and_extra_results_rejected(self):
        for rows in ([], self.raw["cases"][:1], [self.raw["cases"][0]]*2,
                     self.raw["cases"] + [{"id": "extra"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                run.grade(self.catalog, {"cases": rows}, self.score)

    def test_missing_execution_status_and_empty_expectation_rejected(self):
        del self.raw["cases"][0]["error"]
        with self.assertRaises(ValueError):
            run.grade(self.catalog, self.raw, self.score)
        self.catalog["cases"][0]["expected"] = {}
        with self.assertRaises(ValueError):
            run.grade(self.catalog, self.raw, self.score)

    def test_unchanged_is_not_gain(self):
        same = self.record([True, True])
        self.assertEqual("no_quality_gain", run.compare_records(same, same)["verdict"])

    def test_regression_blocks_even_with_one_improvement(self):
        result = run.compare_records(self.record([True, False]), self.record([False, True]))
        self.assertEqual("regression", result["verdict"])
        self.assertEqual(["a"], result["regressed_ids"])

    def test_actual_improvement(self):
        result = run.compare_records(self.record([False, True]), self.record([True, True]))
        self.assertEqual("improved_on_this_control_set", result["verdict"])
        self.assertEqual(50, result["delta_percentage_points"])

    def test_changed_dataset_scorer_probe_model_or_missing_case_rejected(self):
        before = self.record([True, True])
        for name in ("dataset.json", "score.py", "probe.py", "runner.py", "model", "cases"):
            after = copy.deepcopy(before)
            if name == "model":
                after["conditions"]["model"] = "other"
            elif name == "cases":
                after["cases"].pop()
            else:
                after["artifact_sha256"][name] = "other"
            with self.subTest(name=name), self.assertRaises(ValueError):
                run.compare_records(before, after)

    def test_raw_and_source_tampering_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run.write_json(root / "dataset.json", self.catalog)
            run.write_json(root / "raw.json", self.raw)
            (root / "score.py").write_bytes((run.CONTROL / "score.py").read_bytes())
            (root / "probe.py").write_text("# fixture", encoding="utf-8")
            (root / "runner.py").write_text("# fixture", encoding="utf-8")
            run.write_json(root / "dependencies.json", [])
            (root / "source/app").mkdir(parents=True)
            source = root / "source/app/a.py"
            source.write_text("# before", encoding="utf-8")
            cases = run.grade(self.catalog, self.raw, self.score)
            record = {"mode": run.MODE, "status": "complete", "cases": cases, "passed": 2, "total": 2,
                      "conditions": {"dependencies_sha256": run.sha(root / "dependencies.json")},
                      "source_sha256": {"app/a.py": run.sha(source)},
                      "artifact_sha256": {n: run.sha(root/n) for n in ("dataset.json", "raw.json", "score.py", "probe.py", "runner.py")}}
            run.write_json(root / "record.json", record)
            run.validate_record(root / "record.json")
            source.write_text("# altered", encoding="utf-8")
            with self.assertRaises(ValueError):
                run.validate_record(root / "record.json")
            source.write_text("# before", encoding="utf-8")
            run.write_json(root / "raw.json", {"cases": []})
            with self.assertRaises(ValueError):
                run.validate_record(root / "record.json")

    def test_malformed_rows_rejected(self):
        for row in (None, [], {"id": []}, {"id": ""}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                run.grade(self.catalog, {"cases": [row]}, self.score)


if __name__ == "__main__":
    unittest.main()
