"""仅供随机隔离演示库：模型边界使用合成输出，业务 API 保持真实。"""
import json
import runpy
from types import SimpleNamespace

from app.core.config import get_settings
from tests.database_safety import validate_demo_database
from app.services import post_visit_actions as service

if __name__ != '__main__':
    raise RuntimeError('仅允许 python -m tests.postvisit_actions_demo_server')
validate_demo_database(get_settings().async_database_url)


async def recipient(_db):
    return ({'provider':'synthetic','model':'synthetic-model','host':'example.invalid','route_hash':'synthetic'},
            {'api_key':'unused','base_url':'https://example.invalid/v1','default_model':'synthetic-model'})


async def chat(self, **kwargs):
    source = json.loads(kwargs['messages'][0]['content'])
    return SimpleNamespace(content=json.dumps({'follow_ups':[{'description':text,'evidence':text} for text in source['follow_up_items']],
        'medications':[{'name':'示例药','dosage':'1片','evidence':'示例药每次1片每日08:00服用','times':['08:00']}]}))


service.model_recipient = recipient
service.ConsentedLLM.chat = chat
service.enqueue_events = lambda _events: None
runpy.run_module('tests.patient_demo_server', run_name='__main__')
