"""归档验收器反例；使用本阶段固定结果，损坏时必须拒绝。"""
import copy
import unittest
from unittest.mock import patch
from pathlib import Path
import verify

OUTPUT=verify.ROOT/'.ai/tasks/2026-10-08-rag-context/full-final'


class VerifyTests(unittest.TestCase):
    def rejected(self, change):
        result=copy.deepcopy(verify.read(OUTPUT/'results.json'))
        change(result)
        real_read=verify.read
        with patch.object(verify,'read',side_effect=lambda path:result if Path(path)==OUTPUT/'results.json' else real_read(path)):
            with self.assertRaises(ValueError):verify.verify(OUTPUT)

    def test_missing_case_rejected(self):
        self.rejected(lambda r:r['groups']['context1600']['cases'].pop())

    def test_wrong_quote_rejected(self):
        self.rejected(lambda r:r['groups']['context1600']['cases'][0]['sources'][0].update(excerpt='伪造原文'))

    def test_fabricated_score_rejected(self):
        self.rejected(lambda r:r['groups']['context1600']['cases'][0]['score'].update(mrr=999))

    def test_hidden_regression_rejected(self):
        self.rejected(lambda r:r['overall_effect'].update(new_no_answer_candidates=[]))

    def test_network_attempt_rejected(self):
        self.rejected(lambda r:r.update(network_attempts=1))


if __name__=='__main__':unittest.main()
