"""向量调用门禁及原始证据故障注入；fixture不代表真实语义效果。"""
import base64
import copy
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
import resume_experiment as experiment
import resume_embedding as runner
import resume_embedding_verify as verifier
from resume_embedding_runtime import Observer,corpus_snapshot,decode_response,sha,validate_payload

CLI_FAILURES=[]


class EmbeddingTest(unittest.TestCase):
    def response(self,count=24,encoded=True):
        raw=base64.b64encode(struct.pack('<ff',1.0,0.5)).decode() if encoded else [1.0,0.5]
        return {'model':'fixture-model','usage':{'prompt_tokens':72,'total_tokens':72},
                'data':[{'index':i,'embedding':raw} for i in range(count)]}

    def test_float_and_base64_decode_with_native_usage(self):
        expected=[[1.0,0.5]]*24
        for encoded in (False,True):
            vectors,raw=decode_response(self.response(encoded=encoded),24,2)
            self.assertEqual(expected,vectors)
            self.assertEqual({'prompt_tokens':72,'total_tokens':72},raw['usage'])

    def test_missing_usage_order_bool_zero_nan_dimension_rejected(self):
        cases=[]
        for usage in (None,{}, {'prompt_tokens':True},{'prompt_tokens':-1}):
            x=self.response();x['usage']=usage;cases.append(x)
        x=self.response();x['data'][0]['index']=False;cases.append(x)
        x=self.response();x['data'][1]['index']=0;cases.append(x)
        x=self.response();x['data'].reverse();cases.append(x)
        for vector in ([0,0],[1],[1,float('nan')],[1,True],'not-base64'):
            x=self.response();x['data'][0]['embedding']=vector;cases.append(x)
        for x in cases:
            with self.assertRaises((ValueError,TypeError)):decode_response(x,24,2)

    def observer(self,budget=1):
        wire={'model':'fixture-model','input':['合成问题']*24,'encoding_format':'base64'}
        origin=sha(json.dumps(['https','fixture.invalid',None]).encode())
        return Observer(budget,wire,origin)

    def test_transport_budget_wire_origin_and_immediate_checkpoint(self):
        obj=self.observer();request=httpx.Request('POST','https://fixture.invalid/v1/embeddings',json=obj.wire)
        output=io.StringIO()
        with redirect_stdout(output):record=obj.before(request)
        self.assertEqual(record['wire_request'],json.loads(output.getvalue())['http_started']['wire_request'])
        with self.assertRaises(ValueError):obj.before(request)
        for bad in ('zero_budget','origin','body','route'):
            obj=self.observer(0 if bad=='zero_budget' else 1);wire=copy.deepcopy(obj.wire)
            if bad=='body':wire['input'].reverse();wire['input'][0]='不同问题'
            url='https://other.invalid/v1/embeddings' if bad=='origin' else 'https://fixture.invalid/v1/embeddings'
            if bad=='route':url='https://fixture.invalid/v1/chat/completions'
            with self.assertRaises(ValueError):obj.before(httpx.Request('POST',url,json=wire))
            self.assertEqual([],obj.records)

    def test_failure_retains_real_usage_and_finished_checkpoint(self):
        obj=self.observer();out=io.StringIO()
        with redirect_stdout(out):record=obj.before(httpx.Request('POST','https://fixture.invalid/v1/embeddings',json=obj.wire))
        data=self.response();data['data'][0]['embedding']=[0,0]
        with redirect_stdout(out),self.assertRaises(ValueError):Observer.after(record,httpx.Response(200,json=data),24,2)
        self.assertEqual({'prompt_tokens':72,'total_tokens':72},record['native_usage'])
        self.assertIsNone(record['raw_response'])
        self.assertEqual('ValueError',record['response_error_type'])
        self.assertEqual(record,json.loads(out.getvalue().splitlines()[-1])['http_finished'])

    def test_payload_gold_holdout_duplicate_and_budget_rejected(self):
        value=runner.payload('preflight');validate_payload(value)
        cases=[]
        x=copy.deepcopy(value);x['gold']={};cases.append(x)
        x=copy.deepcopy(value);x['questions'][0]['expected_label']='answers';cases.append(x)
        x=copy.deepcopy(value);x['questions'][1]=x['questions'][0];cases.append(x)
        x=copy.deepcopy(value);x['questions']=x['questions'][:16];cases.append(x)
        x=copy.deepcopy(value);x['max_http_requests']=1;cases.append(x)
        x=copy.deepcopy(value);x['mode']='holdout';cases.append(x)
        for x in cases:
            with self.assertRaises(ValueError):validate_payload(x)

    def test_corpus_fingerprint_binds_vectors_content_ids_and_model(self):
        rows=[{'id':str(i),'document_id':'doc','chunk_index':i,'content':'合成原文',
               'embedding_json':[1.0,0.5],'embedding_model':'fixture-model'} for i in range(2)]
        actual=corpus_snapshot(rows,'fixture-model')
        self.assertEqual(actual,corpus_snapshot(list(reversed(rows)),'fixture-model'))
        for field,value in (('embedding_json',[1.0,0.7]),('content','不同原文'),('id','other'),('chunk_index',9)):
            x=copy.deepcopy(rows);x[0][field]=value
            self.assertNotEqual(actual['corpus_sha256'],corpus_snapshot(x,'fixture-model')['corpus_sha256'])
        for field,value in (('embedding_model','other'),('embedding_json',[0,0]),('embedding_json',[1]),('id','1')):
            x=copy.deepcopy(rows);x[0][field]=value
            with self.assertRaises(ValueError):corpus_snapshot(x,'fixture-model')

    def fixture(self,home,mode,plan=None):
        folder=home/mode;folder.mkdir();runner.archive(folder)
        snapshot={'model':'fixture-model','dimension':2,'chunks':2,'corpus_sha256':'a'*64,
                  'sdk_retries':0,'follow_redirects':False,'encoding_format':'base64'}
        value=runner.payload(mode,snapshot if mode=='collect' else None)
        from app.services.text_privacy import redact_for_provider
        wire={'model':snapshot['model'],'input':redact_for_provider([q['query'] for q in value['questions']]),'encoding_format':'base64'}
        key=plan['batch_key'] if plan else None
        records=[];vectors=[]
        if mode=='collect':
            vectors,response=decode_response(self.response(),24,2)
            records=[{'wire_request':wire,'request_sha256':sha(json.dumps(wire,sort_keys=True,ensure_ascii=False).encode()),
                      'status_code':200,'raw_response':response,'native_usage':response['usage'],'response_error_type':None}]
        raw={'protocol':value['protocol'],'mode':mode,'input_sha256':value['input_sha256'],'source_sha256':value['source_sha256'],
             'model_snapshot':snapshot,'wire_request':wire,'questions':value['questions'],'vectors':vectors,'requests':records,
             'status':'success','error_type':None,'elapsed_ms':1.0,'read_only':True,'rolled_back':True,'read_gold':False,
             'settings_before':{},'settings_after':{},'settings_unchanged':True,'forbidden_http_attempts':0,'complete':True}
        runner.write(folder/'execution-input.json',value);runner.write(folder/'observations-raw.json',raw)
        runner.write(folder/'execution.json',{'docker_exit_code':0,'timed_out':False,'batch_key':key,
                     'input_sha256':sha((folder/'execution-input.json').read_bytes()),'evaluation_sha256':runner.hashes()})
        events=[{'runtime_started':{'pid':1,'batch_key':key or 'preflight'}}]
        if records:
            events.extend([{'http_started':{k:records[0][k] for k in ('wire_request','request_sha256')}},{'http_finished':records[0]}])
        events.append({'final':raw})
        (folder/'checkpoints.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        return folder

    def test_independent_verifier_and_cli_failure_injections(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            with patch.object(experiment,'HERE',home),patch.object(runner,'HERE',home),patch.object(verifier,'HERE',home):
                pre=self.fixture(home,'preflight');verifier.verify_preflight(pre)
                plan_dir=home/'plan';runner.prepare(pre,plan_dir);plan=runner.load(plan_dir/'plan.json')
                run=self.fixture(home,'collect',plan)
                reference={'path':str(plan_dir.resolve()),'sha256':sha((plan_dir/'plan.json').read_bytes())}
                runner.write(run/'plan-reference.json',reference)
                # fixture模拟预留，写在临时目录；不构成实际人类授权或供应商调用。
                auth={'status':'approved','source':'human_user_message','message_reference':'fixture-only',
                      'scope':str(home.resolve()),'max_diagnosis_http_requests':24,'max_embedding_http_requests':1}
                allocation={'output':str(run.resolve()),'request_kind':'embedding','reserved_requests':1,'request_keys':[plan['batch_key']],
                            'authorization_sha256':sha(json.dumps(auth,sort_keys=True).encode()),'refund_policy':'fixture'}
                runner.write(run/'allocation-audit.json',{'allocation':allocation,'authorization':auth,'plan_reference':reference})
                (home/'paid-allocations.jsonl').write_text(json.dumps(allocation)+'\n',encoding='utf-8')
                checked=verifier.verify_collect(run,plan_dir)
                self.assertEqual(1,checked['http_requests']);self.assertEqual(24,checked['queries'])
                self.assertIsNone(checked['retrieval_metrics']);self.assertIsNone(checked['clinical_accuracy'])
                code=(f'import sys;sys.path.insert(0,{str(Path(__file__).parent)!r});from pathlib import Path;'
                      f'import resume_embedding_verify as v;import resume_embedding as r;v.HERE=r.HERE=Path({str(home)!r});'
                      f'print(v.verify_collect(Path({str(run)!r}),Path({str(plan_dir)!r}))["status"])')
                positive=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],capture_output=True,text=True)
                self.assertEqual(0,positive.returncode,positive.stderr)
                self.assertIn('VERIFIED_REAL_QUERY_EMBEDDINGS_ONLY',positive.stdout)
                backups={p:p.read_bytes() for p in (run/'observations-raw.json',run/'checkpoints.jsonl',run/'execution-input.json',plan_dir/'plan.json',run/runner.EVAL_FILES[0],run/'plan-reference.json',home/'paid-allocations.jsonl')}
                for kind in ('usage','vector_order','batch_key','missing_checkpoint','gold','scope','source','missing_allocation'):
                    for p,blob in backups.items():p.write_bytes(blob)
                    if kind in ('usage','vector_order','batch_key','missing_checkpoint'):
                        raw=runner.load(run/'observations-raw.json');events=[json.loads(s) for s in (run/'checkpoints.jsonl').read_text(encoding='utf-8').splitlines()]
                        if kind=='usage':raw['requests'][0]['raw_response']['usage']={}
                        elif kind=='vector_order':raw['requests'][0]['raw_response']['data'].reverse()
                        elif kind=='batch_key':events[0]['runtime_started']['batch_key']='wrong'
                        elif kind=='missing_checkpoint':events.pop(1)
                        if kind in ('usage','vector_order'):
                            events[2]={'http_finished':raw['requests'][0]}
                        events[-1]={'final':raw}
                        (run/'observations-raw.json').write_text(json.dumps(raw),encoding='utf-8')
                        (run/'checkpoints.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
                    elif kind=='gold':
                        value=runner.load(run/'execution-input.json');value['gold']={}
                        (run/'execution-input.json').write_text(json.dumps(value),encoding='utf-8')
                    elif kind=='scope':
                        value=runner.load(plan_dir/'plan.json');value['scope']='holdout'
                        (plan_dir/'plan.json').write_text(json.dumps(value),encoding='utf-8')
                        ref={'path':str(plan_dir.resolve()),'sha256':sha((plan_dir/'plan.json').read_bytes())}
                        (run/'plan-reference.json').write_text(json.dumps(ref),encoding='utf-8')
                    elif kind=='source':(run/runner.EVAL_FILES[0]).write_text('changed',encoding='utf-8')
                    else:(home/'paid-allocations.jsonl').write_text('',encoding='utf-8')
                    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    self.assertEqual(1,result.returncode,kind)
                    CLI_FAILURES.append({'case':kind,'exit_code':result.returncode})

    def test_unapproved_embedding_stops_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            with patch.object(experiment,'HERE',home),patch.object(runner,'HERE',home),patch.object(verifier,'HERE',home):
                pre=self.fixture(home,'preflight');plan_dir=home/'plan';runner.prepare(pre,plan_dir)
                auth=home/'auth.json';runner.write(auth,{'status':'approved','source':'human_user_message','message_reference':'fixture-only',
                                                      'scope':str(home.resolve()),'max_diagnosis_http_requests':24})
                with patch.object(runner,'execute') as send,self.assertRaises(ValueError):runner.collect(plan_dir,auth,home/'result')
                send.assert_not_called()
                self.assertFalse((home/'paid-allocations.jsonl').exists())

    def test_direct_paid_execute_without_allocation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(subprocess,'run') as send:
            home=Path(tmp)
            with patch.object(experiment,'HERE',home),patch.object(runner,'HERE',home),self.assertRaises(ValueError):
                runner.execute(runner.payload('collect',{}),home/'run','fake-key')
            send.assert_not_called()
            self.assertFalse((home/'run').exists())


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(EmbeddingTest)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'tests_run':result.testsRun,'success':result.wasSuccessful(),'fixture_only':True,'model_http_requests':0,'cli_failure_injections':CLI_FAILURES},ensure_ascii=False))
    sys.exit(0 if result.wasSuccessful() else 1)
