"""用隔离假数据库核验切换/失败/恢复流程，禁止加载真实应用或调用供应商。"""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch


class SettingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state={'enabled':True,'limit':10,'used':3}
        self.requests=0
        self.updates=[]
        self.fail_request=False
        self.fail_restore=False
        self.conflict=False
        owner=self
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*_):pass
            async def commit(self):pass
            async def execute(self,statement,params):
                owner.updates.append(dict(params))
                if 'SET value=:off' in statement:
                    if owner.conflict:return SimpleNamespace(scalar=lambda:None)
                    owner.state['enabled']=False
                elif params['on']=='true' and owner.fail_restore:
                    raise RuntimeError('simulated_restore_failure')
                else:owner.state['enabled']=True
                return SimpleNamespace(scalar=lambda:'interview_demo.enabled')
        async def policy(_db):return SimpleNamespace(**owner.state)
        async def collect():return {'snapshot':'synthetic'}
        async def embeddings(_encoded,single_attempt=False):
            owner.requests+=1
            owner.assertFalse(owner.state['enabled'])
            owner.assertTrue(single_attempt)
            if owner.fail_request:raise TimeoutError('synthetic_request_failure')
            return {'mode':'real_provider_query_embeddings'}
        sql=ModuleType('sqlalchemy');sql.text=lambda value:value
        db=ModuleType('app.db.session');db.async_session_maker=Session;db.async_engine=SimpleNamespace(echo=True)
        demo=ModuleType('app.services.interview_demo');demo.load_policy=policy
        collector=ModuleType('collect');collector.collect=collect;collector.embeddings=embeddings
        spec=importlib.util.spec_from_file_location('temporary_under_test',Path(__file__).with_name('temporary.py'))
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'sqlalchemy':sql,'app.db.session':db,'app.services.interview_demo':demo,'collect':collector}):
            spec.loader.exec_module(self.module)
        self.payload={'corpus':{'snapshot':'synthetic'},'queries':[f'synthetic-{i}' for i in range(45)],'dataset_sha256':'synthetic'}
    async def test_success_restores_only_enabled(self):
        result=await self.module.run(self.payload)
        self.assertEqual('success',result['status'])
        self.assertTrue(result['restored'])
        self.assertTrue(result['counter_unchanged'])
        self.assertEqual(1,self.requests)
        self.assertTrue(self.state['enabled'])
        self.assertEqual({'interview_demo.enabled'},{p['key'] for p in self.updates})
    async def test_request_failure_still_restores(self):
        self.fail_request=True
        result=await self.module.run(self.payload)
        self.assertEqual('failed',result['status'])
        self.assertTrue(result['restored'])
        self.assertTrue(self.state['enabled'])
        self.assertEqual(1,self.requests)
    async def test_concurrent_setting_conflict_never_calls_provider(self):
        self.conflict=True
        result=await self.module.run(self.payload)
        self.assertEqual('failed',result['status'])
        self.assertEqual(0,self.requests)
        self.assertTrue(self.state['enabled'])
    async def test_restore_failure_cannot_return_success(self):
        self.fail_restore=True
        with self.assertRaises(RuntimeError):await self.module.run(self.payload)
        self.assertFalse(self.state['enabled'])


if __name__=='__main__':unittest.main()
