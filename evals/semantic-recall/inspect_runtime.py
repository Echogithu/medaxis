"""只读检查本地后端健康与三项演示设置；不读取身份、密钥或患者。"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess


CODE='''import asyncio,hashlib,json,urllib.request
from sqlalchemy import select,text
from app.db.session import async_session_maker,async_engine
from app.models.config import SystemSetting
async def main():
    async_engine.echo=False
    async with async_session_maker() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        rows=(await db.execute(select(SystemSetting.key,SystemSetting.value).where(
            SystemSetting.key.in_(['interview_demo.enabled','interview_demo.limit','interview_demo.used'])))).all()
        values={k.removeprefix('interview_demo.'):v for k,v in rows}
        await db.rollback()
    response=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5)
    print(json.dumps({'settings':values,'health_http_status':response.status,
        'rag_on_disk_sha256':hashlib.sha256(open('/app/app/services/rag.py','rb').read()).hexdigest(),
        'read_only':True,'provider_calls':0,'api_code_loaded':None}))
try:asyncio.run(main())
except Exception as exc:print(json.dumps({'status':'failed','error_type':type(exc).__name__}));raise SystemExit(1)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('拒绝覆盖现有记录')
    p=subprocess.run(['docker','exec','-i','-w','/app','medaxis-backend','python','-'],
                     input=CODE,capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise ValueError('运行态读取失败；没有进行任何设置写入')
    result=json.loads(p.stdout)
    if result['settings']['enabled']!='false' or result['health_http_status']!=200:raise ValueError('保护状态或健康检查不符合本轮要求')
    result['recorded_at']=datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
