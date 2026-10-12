"""真实归档及8种损坏反例；不重跑模型、不修改验证题或结果。"""
import unittest
from verify import verify
from runner import ROOT,TASK,read


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.output=TASK/'old45-final';self.result=read(self.output/'results.json')
        self.paths=(ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json',
                    TASK/'post-url-snapshot/results.json',ROOT/'.ai/tasks/2026-10-07-rag-baseline/query-embeddings.json')
    def check(self):return verify(self.output,*self.paths,result=self.result)
    def reject(self):
        with self.assertRaises((ValueError,KeyError)):self.check()
    def test_real(self):self.check()
    def test_missing_case(self):self.result['groups']['after']['cases'].pop();self.reject()
    def test_missing_group(self):del self.result['groups']['before'];self.reject()
    def test_input_hash(self):self.result['dataset_sha256']='0'*64;self.reject()
    def test_network(self):self.result['network_attempts']=1;self.reject()
    def test_fake_url(self):self.result['groups']['after']['cases'][0]['serialized_sources'][0]['url']='https://unverified.example';self.reject()
    def test_fake_cosine(self):self.result['groups']['after']['cases'][0]['serialized_sources'][0]['retrieval_score']=1.;self.reject()
    def test_fake_excerpt(self):self.result['groups']['after']['cases'][0]['sources'][0]['excerpt']+='虚构';self.reject()
    def test_fake_summary(self):self.result['groups']['after']['summary']['mrr']=1.;self.reject()


if __name__=='__main__':unittest.main()
