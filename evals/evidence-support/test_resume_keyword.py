"""关键词坐标投影单测及已存真实记录的隔离篡改验收，不联网。"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from resume_experiment import HERE,load
from resume_keyword_runtime import project,sha

FAILURES=[]


class KeywordTest(unittest.TestCase):
    def test_projection_requires_unique_raw_and_verified_context_coordinates(self):
        text='开头 原文 后续'
        doc={'content':text,'sha256':sha(text.encode()),'title':'fixture','source_url':'https://fixture.invalid'}
        chunk={'document_id':'d','document_title':'fixture','source_url':doc['source_url'],'content':'原文'}
        expected={'document_id':'d','start':3,'end':5,'quote':'原文'}
        self.assertEqual([expected],project([chunk],{'d':doc}))
        self.assertEqual([expected],project([chunk,chunk],{'d':doc}))
        with self.assertRaises(ValueError):project([chunk],{'d':{**doc,'content':'原文 原文'}})
        changed={**chunk,'context_metadata':{'start':3,'end':5,'source_text_sha256':'wrong'}}
        with self.assertRaises(ValueError):project([changed],{'d':doc})
        with self.assertRaises(ValueError):project([{**chunk,'content':'伪造正文'}],{'d':doc})

    def test_actual_record_tampering_is_rejected_in_isolated_cli(self):
        original=HERE/'keyword-context-v1'
        self.assertTrue((original/'score.json').exists(),'必须先有真实只读记录，不用fixture冒充实际检索')
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);folder=home/'fixture-copy';shutil.copytree(original,folder)
            originals={n:(folder/n).read_bytes() for n in ('observations-raw.json','execution-input.json','checkpoints.jsonl')}
            raw=load(folder/'observations-raw.json');cases={}
            for name in ('missing_result','duplicate_id','wrong_quote','model_attempt','full_pipeline_claim'):
                x=copy.deepcopy(raw)
                if name=='missing_result':x['rows'].pop()
                elif name=='duplicate_id':x['rows'][1]['id']=x['rows'][0]['id']
                elif name=='wrong_quote':x['rows'][0]['raw_sources'][0]['quote']='伪造正文'
                elif name=='model_attempt':x['counts']['unexpected_model']=1
                else:x['full_production_pipeline']=True
                cases[name]=('observations-raw.json',json.dumps(x,ensure_ascii=False).encode())
            x=load(folder/'execution-input.json');x['gold']={}
            cases['gold_leak']=('execution-input.json',json.dumps(x).encode())
            cases['missing_checkpoint']=('checkpoints.jsonl','\n'.join(originals['checkpoints.jsonl'].decode().splitlines()[1:]).encode())
            code='import sys;from pathlib import Path;import resume_keyword_verify as v;v.HERE=Path(sys.argv[1]);v.verify(Path(sys.argv[2]))'
            for name,(target,data) in cases.items():
                for n,contents in originals.items():(folder/n).write_bytes(contents)
                (folder/target).write_bytes(data)
                if target=='observations-raw.json':
                    x=json.loads(data);events=[{'checkpoint':r} for r in x['rows']]+[{'final':x}]
                    (folder/'checkpoints.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
                result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,str(home),str(folder)],
                                      cwd=Path(__file__).parent,capture_output=True,text=True,encoding='utf-8')
                self.assertNotEqual(0,result.returncode,name);self.assertIn('ValueError',result.stderr,name)
                FAILURES.append({'case':name,'exit_code':result.returncode})


if __name__=='__main__':
    run=unittest.main(verbosity=2,exit=False)
    print(json.dumps({'model_http_requests':0,'isolated_mutations_only':True,'failure_injection_exits':FAILURES}))
    sys.exit(0 if run.result.wasSuccessful() else 1)
