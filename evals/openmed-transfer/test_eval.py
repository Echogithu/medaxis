"""评分器反例和离线接口测试；使用 unittest 避开应用数据库 fixture。"""

import copy
import json
import sys
import unittest

import candidate
import run_eval


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(run_eval.CATALOG.read_text(encoding="utf-8"))
        cls.funcs = run_eval.load_baseline()

    def case(self, cid):
        return copy.deepcopy(next(c for c in self.catalog["cases"] if c["id"] == cid))

    def reference_output(self, case):
        """测试评分器用的人造正确输出，不参与候选评测。"""
        output = run_eval.baseline_process(case["input"], self.funcs)
        output["assertions"] = copy.deepcopy(case["gold"]["assertions"])
        output["redactions"] = copy.deepcopy(case["gold"]["pii"])
        text = list(case["input"]["text"])
        for span in output["redactions"]:
            text[span["start"]:span["end"]] = "*" * (span["end"] - span["start"])
        output["redacted_text"] = "".join(text)
        output["claims"] = [{"id": c["id"], "verdict": "accepted" if c["supported"] else "rejected"}
                            for c in case["gold"]["claims"]]
        return output

    def test_frozen_catalog_and_splits(self):
        self.assertEqual([], run_eval.validate_catalog(self.catalog))
        self.assertEqual(12, sum(c["split"] == "development" for c in self.catalog["cases"]))
        self.assertEqual(12, sum(c["split"] == "evaluation" for c in self.catalog["cases"]))

    def test_correct_output_is_distinct_from_missing_and_wrong(self):
        case = self.case("D08")
        correct = run_eval.score(case, self.reference_output(case))
        self.assertEqual([], correct["contract_errors"])
        self.assertEqual(0, correct["privacy"]["leaked_chars"])
        self.assertTrue(all(a["correct"] for a in correct["assertions"]))
        missing = run_eval.score(case, {})
        self.assertTrue(missing["contract_errors"])
        self.assertGreater(missing["privacy"]["leaked_chars"], 0)
        self.assertFalse(missing["assertions"][0]["correct"])
        wrong = self.reference_output(case)
        wrong["assertions"][0]["status"] = "non_patient"
        self.assertFalse(run_eval.score(case, wrong)["assertions"][0]["correct"])

    def test_privacy_labels_without_actual_redaction_fail(self):
        case = self.case("D08")
        output = self.reference_output(case)
        output["redacted_text"] = case["input"]["text"]
        scored = run_eval.score(case, output)
        self.assertIn("标记位置与实际遮蔽不一致", scored["contract_errors"])
        self.assertEqual(0, scored["privacy"]["detected_gold_chars"])

    def test_changed_name_or_phone_is_not_accepted_as_masking(self):
        case = self.case("D08")
        output = self.reference_output(case)
        text = list(case["input"]["text"])
        for span in output["redactions"]:
            replacement = "王一二" if span["label"] == "NAME" else "13911111111"
            text[span["start"]:span["end"]] = replacement
        output["redacted_text"] = "".join(text)
        scored = run_eval.score(case, output)
        self.assertTrue(scored["contract_errors"])
        self.assertEqual(0, scored["privacy"]["detected_gold_chars"])
        self.assertEqual(scored["privacy"]["gold_chars"], scored["privacy"]["leaked_chars"])

    def test_empty_or_malformed_package_fails_contract(self):
        case = self.case("D06")
        for malformed in ({}, {"known_facts": {}, "unknown_facts": [], "unresolved_facts": []}):
            output = self.reference_output(case)
            output["package"] = malformed
            scored = run_eval.score(case, output)
            self.assertTrue(scored["contract_errors"])
            self.assertFalse(scored["raw_history_preserved"])

    def test_overredaction_is_counted_and_clinical_values_are_protected(self):
        case = self.case("D10")
        output = self.reference_output(case)
        output["redacted_text"] = "*" * len(case["input"]["text"])
        output["redactions"] = [{"start": 0, "end": len(output["redacted_text"])}]
        scored = run_eval.score(case, output)
        self.assertGreater(scored["privacy"]["false_redacted_chars"], 0)
        self.assertEqual(0, scored["protected"]["preserved"])

    def test_duplicate_or_out_of_range_predictions_fail_contract(self):
        case = self.case("D01")
        output = self.reference_output(case)
        output["assertions"].append(copy.deepcopy(output["assertions"][0]))
        output["redactions"] = [{"start": -1, "end": 999}]
        output["claims"].append(copy.deepcopy(output["claims"][0]))
        self.assertGreaterEqual(len(run_eval.score(case, output)["contract_errors"]), 3)

    def test_unsupported_claim_admission_is_not_a_pass(self):
        case = self.case("D01")
        base = run_eval.baseline_process(case["input"], self.funcs)
        scored = run_eval.score(case, base)
        unsupported = next(c for c in scored["claims"] if not c["supported"])
        self.assertEqual("accepted", unsupported["verdict"])
        candidate_result = candidate.process(case["input"], base)
        self.assertEqual("review", candidate_result["claims"][1]["verdict"])

    def test_partial_quote_cannot_remove_negation(self):
        case = self.case("E11")
        base = run_eval.baseline_process(case["input"], self.funcs)
        self.assertEqual("accepted", base["claims"][0]["verdict"])
        self.assertEqual("review", candidate.process(case["input"], base)["claims"][0]["verdict"])

    def test_correct_paraphrase_is_explicitly_withheld_not_called_false(self):
        case = self.case("E12")
        base = run_eval.baseline_process(case["input"], self.funcs)
        result = candidate.process(case["input"], base)
        self.assertEqual("review", result["claims"][0]["verdict"])
        scored = run_eval.score(case, result)
        self.assertTrue(scored["claims"][0]["supported"])

    def test_unknown_and_conflicting_answers_keep_real_preparation_semantics(self):
        for cid in ("D06", "D07", "D12"):
            with self.subTest(cid=cid):
                case = self.case(cid)
                output = run_eval.baseline_process(case["input"], self.funcs)
                self.assertTrue(run_eval.score(case, output)["raw_history_preserved"])
        self.assertNotIn("app.db.session", sys.modules)

    def test_family_and_denied_findings_do_not_become_current_patient_findings(self):
        case = self.case("E02")
        output = candidate.process(case["input"], run_eval.baseline_process(case["input"], self.funcs))
        self.assertEqual(["non_patient", "refuted"], [a["status"] for a in output["assertions"]])

    def test_unknown_scope_does_not_erase_another_clause(self):
        case = self.case("E10")
        output = candidate.process(case["input"], run_eval.baseline_process(case["input"], self.funcs))
        self.assertEqual(["unknown", "present"], [a["status"] for a in output["assertions"]])

    def test_catalog_invalid_offsets_and_labels_are_rejected(self):
        invalid = copy.deepcopy(self.catalog)
        invalid["cases"][0]["gold"]["assertions"][0]["end"] = 999
        invalid["cases"][0]["gold"]["assertions"][0]["status"] = "made-up"
        self.assertGreaterEqual(len(run_eval.validate_catalog(invalid)), 2)

    def test_missing_supported_claims_are_not_counted_as_admitted(self):
        case = self.case("D01")
        output = self.reference_output(case)
        output["claims"] = []
        scored = run_eval.score(case, output)
        self.assertTrue(scored["contract_errors"])
        self.assertEqual(["missing", "missing"], [c["verdict"] for c in scored["claims"]])


if __name__ == "__main__":
    unittest.main()
