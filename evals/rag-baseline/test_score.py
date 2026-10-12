"""量尺反例与原文定位验证；不加载应用、不连接数据库或模型。"""
import copy
import hashlib
import unittest
from score import score,summarize,covers
from build import validate


class ScoreTests(unittest.TestCase):
    def setUp(self):
        content='abcdefghij'
        self.documents={'d':{'id':'d','content':content,'text_sha256':hashlib.sha256(content.encode()).hexdigest()}}
        self.unit={'id':'e','document_id':'d','document_sha256':self.documents['d']['text_sha256'],
                   'start':2,'end':8,'quote':'cdefgh','qualifiers':[{'start':6,'end':8,'text':'gh'}],'split':'development'}
        self.case={'id':'a','topic_id':'e','split':'development','query':'question','expected_action':'retrieve_evidence','gold_ids':['e']}
    def source(self,a,b):
        return {'document_id':'d','start':a,'end':b,'excerpt':self.documents['d']['content'][a:b]}
    def test_correct_wrong_and_missing(self):
        good=score(self.case,{'e':self.unit},[self.source(2,8)],self.documents)
        self.assertEqual(1,good['evidence_recall_at_k'])
        self.assertEqual(0,score(self.case,{'e':self.unit},[],self.documents)['evidence_recall_at_k'])
        self.assertFalse(score(self.case,{'e':self.unit},[self.source(0,2)],self.documents)['hit_at_k'])
    def test_hit_is_not_complete_recall_or_conditions(self):
        partial=score(self.case,{'e':self.unit},[self.source(2,5)],self.documents)
        self.assertTrue(partial['hit_at_k'])
        self.assertEqual(0,partial['evidence_recall_at_k'])
        self.assertEqual(0,partial['qualifier_recall'])
    def test_adjacent_chunks_cover_but_gap_does_not(self):
        self.assertTrue(covers([(2,5),(5,8)],2,8))
        self.assertFalse(covers([(2,4),(5,8)],2,8))
        combined=score(self.case,{'e':self.unit},[self.source(2,5),self.source(5,8)],self.documents)
        self.assertTrue(combined['complete_evidence'])
    def test_fabricated_excerpt_or_location_rejected(self):
        source=self.source(2,8)
        source['excerpt']='invented'
        with self.assertRaises(ValueError):score(self.case,{'e':self.unit},[source],self.documents)
    def test_no_answer_separate_denominator(self):
        case={**self.case,'gold_ids':[],'expected_action':'no_evidence'}
        result=score(case,{},[],self.documents)
        self.assertIsNone(result['evidence_recall_at_k'])
        self.assertFalse(result['unsupported_candidate_returned'])
        self.assertTrue(score(case,{},[self.source(0,2)],self.documents)['unsupported_candidate_returned'])
    def test_empty_duplicate_missing_and_failed_execution(self):
        good={'id':'a','status':'success','score':score(self.case,{'e':self.unit},[],self.documents)}
        for rows in ([],[good,good],[{**good,'id':'unknown'}]):
            with self.assertRaises(ValueError):summarize([self.case],rows)
        failed=summarize([self.case],[{'id':'a','status':'failed'}])
        self.assertIsNone(failed['quality_metrics'])
    def test_gold_tampering_and_split_leak_rejected(self):
        corpus={'documents':list(self.documents.values())}
        dataset={'gold_units':[self.unit],'cases':[self.case]}
        validate(corpus,dataset)
        broken=copy.deepcopy(dataset)
        broken['gold_units'][0]['quote']='different'
        with self.assertRaises(ValueError):validate(corpus,broken)
        broken=copy.deepcopy(dataset)
        broken['cases'][0]['split']='evaluation'
        with self.assertRaises(ValueError):validate(corpus,broken)

    def test_duplicate_gold_and_invalid_ranges_rejected(self):
        corpus={'documents':list(self.documents.values())}
        dataset={'gold_units':[self.unit],'cases':[self.case]}
        duplicate=copy.deepcopy(dataset)
        duplicate['gold_units'].append(copy.deepcopy(self.unit))
        with self.assertRaises(ValueError):validate(corpus,duplicate)
        invalid=copy.deepcopy(dataset)
        invalid['gold_units'][0].update(start=5,end=5,quote='')
        with self.assertRaises(ValueError):validate(corpus,invalid)

    def test_duplicate_expected_cases_rejected(self):
        row={'id':'a','status':'success','score':score(self.case,{'e':self.unit},[],self.documents)}
        with self.assertRaises(ValueError):summarize([self.case,self.case],[row])


if __name__=='__main__':unittest.main()
