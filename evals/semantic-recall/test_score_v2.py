"""评分校准独立反例；不读取当前45题检索结果。"""
import unittest
from score_v2 import covers_text


class CoverageTests(unittest.TestCase):
    def test_newline_gap_can_be_ignored(self):
        self.assertTrue(covers_text([(0,2),(3,5)],0,5,'甲乙\n丙丁'))
    def test_missing_negation_is_not_ignored(self):
        self.assertFalse(covers_text([(0,2),(3,5)],0,5,'服药不适用'))
    def test_missing_number_is_not_ignored(self):
        self.assertFalse(covers_text([(0,2),(3,5)],0,5,'年龄3个月'))
    def test_missing_punctuation_is_not_ignored(self):
        self.assertFalse(covers_text([(0,2),(3,5)],0,5,'甲乙；丙丁'))
    def test_trailing_whitespace_and_missing_body_differ(self):
        self.assertTrue(covers_text([(0,2)],0,4,'甲乙 \n'))
        self.assertFalse(covers_text([(0,2)],0,4,'甲乙丙丁'))


if __name__=='__main__':unittest.main()
