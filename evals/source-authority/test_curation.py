"""核验资料更新前的漂移、越域与重复文档拒绝条件；不访问数据库。"""
import copy
import unittest
from curate import validate
from runner import TASK,read


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.manifest=read(TASK/'source-authority-manifest.json')
        self.corpus=read(TASK/'initial-snapshot/results.json')

    def check(self):return validate(self.manifest,self.corpus,TASK/'official-downloads')

    def test_verified_four(self):self.assertEqual(4,len(self.check()))
    def test_duplicate(self):
        self.manifest['documents'][1]=copy.deepcopy(self.manifest['documents'][0])
        with self.assertRaises(ValueError):self.check()
    def test_wrong_host(self):
        self.manifest['documents'][0]['new_source_url']='https://unverified.example/a.pdf'
        with self.assertRaises(ValueError):self.check()
    def test_changed_content(self):
        self.corpus['documents'][0]['content']+='X'
        with self.assertRaises(ValueError):self.check()
    def test_changed_old_url(self):
        self.corpus['documents'][0]['source_url']='https://www.nhc.gov.cn/other'
        with self.assertRaises(ValueError):self.check()
    def test_wrong_pdf_hash(self):
        self.manifest['documents'][0]['pdf_sha256']='0'*64
        with self.assertRaises(ValueError):self.check()


if __name__=='__main__':unittest.main()
