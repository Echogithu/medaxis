"""仅在用户明确授权后执行一次本地演示设置切换；finally恢复并校验原值。"""
import asyncio
import base64
import json
import logging
import time
from datetime import datetime,timezone
from sqlalchemy import text
from app.db.session import async_session_maker,async_engine
from app.services.interview_demo import load_policy
from collect import collect,embeddings


async def run(payload):
    async_engine.echo=False
    logging.disable(logging.CRITICAL)
    current=await collect()
    if current!=payload['corpus']:
        raise ValueError('当前语料、配置或源码与冻结快照不同，禁止切换')
    queries=payload['queries']
    if len(queries)!=45 or len(set(queries))!=45:
        raise ValueError('本次只允许已冻结的45条唯一合成查询')
    before=None
    changed=False
    restored=False
    artifact=None
    failure=None
    opened=None
    closed=None
    try:
        async with async_session_maker() as db:
            policy=await load_policy(db)
            if not policy.enabled:
                raise ValueError('演示保护当前未开启，不擅自推定恢复值')
            before={'enabled':policy.enabled,'limit':policy.limit,'used':policy.used}
            # 原值必须仍为true，否则并发配置修改时拒绝覆盖。
            row=await db.execute(text("UPDATE system_settings SET value=:off WHERE key=:key AND value=:on RETURNING key"),
                                 {'off':'false','on':'true','key':'interview_demo.enabled'})
            if row.scalar() is None:
                raise ValueError('并发设置变更，未执行切换')
            # 在提交前设置恢复标志，连接在提交后异常时仍尝试查证/恢复。
            changed=True
            opened=time.perf_counter()
            await db.commit()
        encoded=base64.b64encode(json.dumps(queries,ensure_ascii=False).encode()).decode()
        artifact=await asyncio.wait_for(embeddings(encoded,single_attempt=True),timeout=45)
    except Exception as exc:
        failure=type(exc).__name__
    finally:
        if changed:
            async with async_session_maker() as db:
                row=await db.execute(text("UPDATE system_settings SET value=:on WHERE key=:key AND value=:off RETURNING key"),
                                     {'on':'true','off':'false','key':'interview_demo.enabled'})
                await db.commit()
                policy=await load_policy(db)
                restored=policy.enabled
                after={'enabled':policy.enabled,'limit':policy.limit,'used':policy.used}
                closed=time.perf_counter()
                if not restored:
                    raise RuntimeError('演示保护恢复检查失败，必须停止后续工作')
        else:
            after=before
    return {'status':'success' if artifact is not None and failure is None and restored else 'failed',
            'recorded_at':datetime.now(timezone.utc).isoformat(),'error_type':failure,
            'before':before,'after':after,'restored':restored,
            'counter_unchanged':before is not None and before==after,
            'disabled_seconds':round(closed-opened,3) if closed is not None else None,
            'dataset_sha256':payload['dataset_sha256'],'artifact':artifact}


async def main(payload):
    try:
        result=await run(payload)
    except Exception as exc:
        result={'status':'failed','error_type':type(exc).__name__,'restored':'not_confirmed'}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result['status']=='success' else 1
