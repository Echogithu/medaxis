"""三路检索控制及来源/余弦门禁测试；fixture不提供质量提升证据。"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import resume_experiment as experiment
import resume_retrieval as runner
import resume_retrieval_verify as verifier
from resume_retrieval_runtime import validate_payload

HERE=experiment.HERE
CLI_FAILURES=[]


class RetrievalTest(unittest.TestCase):
    def test_preflight_payload_has_no_gold_holdout_or_fake_vectors(self):
        value=runner.payload('preflight',HERE/'embedding-preflight-v2');validate_payload(value)
        cases=[]
        x=copy.deepcopy(value);x['gold']={};cases.append(x)
        x=copy.deepcopy(value);x['questions'][0]['expected_label']='answers';cases.append(x)
        x=copy.deepcopy(value);x['questions'][1]=x['questions'][0];cases.append(x)
        x=copy.deepcopy(value);x['top_k']=5;cases.append(x)
        x=copy.deepcopy(value);x['vectors']=[[1,0]]*24;cases.append(x)
        for x in cases:
            with self.assertRaises(ValueError):validate_payload(x)

    def test_direct_run_without_real_vectors_stops_before_docker(self):
        value=runner.payload('preflight',HERE/'embedding-preflight-v2');value['mode']='run'
        value['vectors']=[[1.0]+[0.0]*1535 for _ in range(24)];value['vector_evidence_sha256']='a'*64
        validate_payload(value)
        with tempfile.TemporaryDirectory() as tmp,patch.object(subprocess,'run') as transport:
            home=Path(tmp);missing=HERE/'uncollected-fixture-vector'
            self.assertFalse(missing.exists())
            reference={'preflight':str(HERE/'embedding-preflight-v2'),'vector_run':str(missing),'vector_plan':str(HERE/'uncollected-fixture-plan')}
            with self.assertRaises(FileNotFoundError):runner.execute(value,home/'output',reference)
            transport.assert_not_called();self.assertFalse((home/'output').exists())

    def rows(self):
        docs={'doc1':{'content':'第一证据。'},'doc2':{'content':'第二证据。'}}
        chunks={f'00000000-0000-0000-0000-{i:012d}':{'id':f'00000000-0000-0000-0000-{i:012d}',
                'document_id':f'doc{i}','chunk_index':0,'content':docs[f'doc{i}']['content'],
                'embedding_model':'fixture-model','embedding_json':[1,0] if i==1 else [0,1]} for i in (1,2)}
        anchors=[{'chunk_id':c['id'],**{k:c[k] for k in ('document_id','chunk_index','content')},
                  'rank':1.0 if c['document_id']=='doc1' else 0.0,'retrieval_model':'fixture-model',
                  'retrieval_dimension':2,'retrieval_score':1.0 if c['document_id']=='doc1' else 0.0} for c in chunks.values()]
        sources=[{'document_id':c['document_id'],'start':0,'end':len(c['content']),'quote':c['content']} for c in chunks.values()]
        row={'id':'fixture-question','variant':'semantic','status':'success','error_type':None,'anchors':anchors,
             'raw_sources':sources,'context_sources':copy.deepcopy(sources),'search_ms':1.0,'context_ms':0.1}
        return row,chunks,docs

    def test_semantic_exact_order_cosine_and_raw_context_valid(self):
        row,chunks,docs=self.rows();question={'id':row['id'],'query':'合成问题'}
        verifier.validate_row(row,question,[1,0],'fixture-model',chunks,docs)
        self.assertAlmostEqual(0,verifier.cosine([1,0],[0,1]))
        for variant in ('keyword','hybrid'):
            x=copy.deepcopy(row);x['variant']=variant
            if variant=='keyword':
                for anchor in x['anchors']:
                    anchor['rank']=0
                    for key in ('retrieval_model','retrieval_dimension','retrieval_score'):anchor.pop(key)
            verifier.validate_row(x,question,[1,0],'fixture-model',chunks,docs)

    def test_wrong_score_order_context_origin_duplicates_errors_rejected(self):
        row,chunks,docs=self.rows();question={'id':row['id'],'query':'合成问题'};cases=[]
        x=copy.deepcopy(row);x['anchors'][0]['retrieval_score']=0.5;cases.append(x)
        x=copy.deepcopy(row);x['anchors'].reverse();x['raw_sources'].reverse();x['context_sources'].reverse();cases.append(x)
        x=copy.deepcopy(row);x['anchors'][0]['retrieval_model']='other';cases.append(x)
        x=copy.deepcopy(row);x['anchors'].append(x['anchors'][0]);cases.append(x)
        x=copy.deepcopy(row);x['context_sources'][0]['quote']='伪造引文';cases.append(x)
        x=copy.deepcopy(row);x['status']='error';x['error_type']='timeout';cases.append(x)
        x=copy.deepcopy(row);x['search_ms']=float('nan');cases.append(x)
        x=copy.deepcopy(row);x['anchors'][0]['rank']=True;cases.append(x)
        for x in cases:
            with self.assertRaises(ValueError):verifier.validate_row(x,question,[1,0],'fixture-model',chunks,docs)

    def test_summary_keeps_fixed_denominators_and_no_answer_rate(self):
        at_k={str(k):{'hit':True,'annotated_evidence_recall':1,'complete_evidence':True,
                     'necessary_claim_coverage':True,'mrr':1,'unsupported_returned':None} for k in (5,10)}
        rows=[{'answerable':True,'at_k':copy.deepcopy(at_k),'source_chars':10} for _ in range(20)]
        for _ in range(4):
            scores={str(k):{'unsupported_returned':True} for k in (5,10)}
            rows.append({'answerable':False,'at_k':scores,'source_chars':10})
        checked=verifier.summarize(rows)
        self.assertEqual(1,checked['at_k']['10']['no_answer_false_retrieval_rate'])
        self.assertEqual(240,checked['source_chars'])
        with self.assertRaises(ValueError):verifier.summarize(rows[:-1])

    def test_real_preflight_record_and_cli_mutations(self):
        source=HERE/'retrieval-preflight-v2'
        self.assertTrue(source.exists(),'先完成零模型真实预检；不能skip冒充通过')
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'preflight';shutil.copytree(source,folder)
            code=(f'import sys;sys.path.insert(0,{str(Path(__file__).parent)!r});from pathlib import Path;'
                  f'import resume_retrieval_verify as v;v.HERE=Path({str(home)!r});'
                  f'print(v.verify(Path({str(folder)!r}))["status"])')
            positive=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],capture_output=True,text=True)
            self.assertEqual(0,positive.returncode,positive.stderr)
            self.assertIn('PASS_REAL_RETRIEVAL_PIPELINE_PREFLIGHT_ONLY',positive.stdout)
            paths=(folder/'observations-raw.json',folder/'checkpoints.jsonl',folder/runner.EVAL_FILES[0],folder/'execution-input.json')
            backups={p:p.read_bytes() for p in paths}
            for kind in ('fake_query_embedding','network_attempt','missing_checkpoint','source_change','gold'):
                for p,blob in backups.items():p.write_bytes(blob)
                if kind in ('fake_query_embedding','network_attempt'):
                    raw=runner.load(folder/'observations-raw.json')
                    if kind=='fake_query_embedding':raw['technical_probe']['query_embedding_generated']=True
                    else:raw['counts']['forbidden_http']=1
                    (folder/'observations-raw.json').write_text(json.dumps(raw),encoding='utf-8')
                    events=[json.loads(s) for s in (folder/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines()]
                    events[-1]={'final':raw};(folder/'checkpoints.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
                elif kind=='missing_checkpoint':
                    events=(folder/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines()[1:]
                    (folder/'checkpoints.jsonl').write_text('\n'.join(events)+'\n',encoding='utf-8')
                elif kind=='source_change':(folder/runner.EVAL_FILES[0]).write_text('changed',encoding='utf-8')
                else:
                    value=runner.load(folder/'execution-input.json');value['gold']={}
                    (folder/'execution-input.json').write_text(json.dumps(value),encoding='utf-8')
                result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],capture_output=True,text=True)
                self.assertEqual(1,result.returncode,kind);CLI_FAILURES.append({'case':kind,'exit_code':result.returncode})


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RetrievalTest))
    print(json.dumps({'tests_run':result.testsRun,'success':result.wasSuccessful(),'fixture_only':True,'model_http_requests':0,'cli_failure_injections':CLI_FAILURES},ensure_ascii=False))
    sys.exit(0 if result.wasSuccessful() else 1)
