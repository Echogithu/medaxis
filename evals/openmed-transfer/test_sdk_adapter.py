"""保护真实 SDK 与等长评分协议之间的偏移边界。"""
import unittest

from sdk_adapter import context_assertions, mask_spans


class AdapterTests(unittest.TestCase):
    def test_overlapping_spans_preserve_original_coordinates(self):
        self.assertEqual("a***e", mask_spans("abcde", [
            {"start": 1, "end": 3, "text": "bc"},
            {"start": 2, "end": 4, "text": "cd"}]))

    def test_outside_or_non_integer_coordinates_are_rejected(self):
        for start, end in [(-1, 1), (0, 6), (False, 1), (0, 1.0), (1, 1)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                mask_spans("abcde", [{"start": start, "end": end, "text": "a"}])

    def test_mismatched_entity_text_is_rejected(self):
        with self.assertRaises(ValueError):
            mask_spans("中文", [{"start": 0, "end": 1, "text": "文"}])

    def test_actual_sdk_negation_axes_are_preserved(self):
        mapped, raw = context_assertions({"text": "没有咳嗽", "mentions": [
            {"start": 2, "end": 4, "text": "咳嗽"}]})
        self.assertEqual("refuted", mapped[0]["status"])
        self.assertEqual("negated", raw[0]["negation"])


if __name__ == "__main__":
    unittest.main()
