"""同一Goal的对话/向量请求共用预留账本；不推断授权，不自动退款。"""
import hashlib
import json
import os
from contextlib import contextmanager


def require(condition, message):
    if not condition: raise ValueError(message)


@contextmanager
def ledger_lock(path):
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def allocate(home, authorization, keys, output, *, kind='diagnosis'):
    home=home.resolve();output=output.resolve()
    output.relative_to(home)
    require(output!=home and not output.exists(),'仅允许新的Goal运行目录')
    require(kind in {'diagnosis','embedding'},'未知请求类别')
    required={'status','source','message_reference','max_diagnosis_http_requests','scope'}
    require(set(authorization) in (required,required|{'max_embedding_http_requests'}),'额度合同字段非法')
    require(authorization['status']=='approved' and authorization['source']=='human_user_message'
            and isinstance(authorization['message_reference'],str) and bool(authorization['message_reference'].strip())
            and authorization['scope']==str(home),'本Goal缺少新额度授权')
    limits={'diagnosis':authorization['max_diagnosis_http_requests'],'embedding':authorization.get('max_embedding_http_requests',0)}
    require(type(limits['diagnosis']) is int and limits['diagnosis']>0
            and type(limits['embedding']) is int and limits['embedding']>=0,'调用上限必须明确；未授权embedding为0')
    require(isinstance(keys,list) and bool(keys) and all(isinstance(k,str) and k.strip() for k in keys)
            and len(keys)==len(set(keys)),'预留任务key为空或重复')
    ledger=home/'paid-allocations.jsonl'
    with ledger_lock(home/'paid-allocations.lock'):
        prior=[json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
        totals={'diagnosis':0,'embedding':0};used=set()
        for record in prior:
            category=record.get('request_kind','diagnosis')
            require(category in totals and type(record['reserved_requests']) is int
                    and record['reserved_requests']==len(record['request_keys'])>0
                    and len(record['request_keys'])==len(set(record['request_keys'])),'已有账本损坏，停止')
            require(not used.intersection(record['request_keys']),'账本已有重复key，停止')
            used.update(record['request_keys']);totals[category]+=record['reserved_requests']
        require(not used.intersection(keys),'任务已有预留/尝试，禁止未知状态自动重发')
        require(all(totals[k]<=limits[k] for k in totals) and totals[kind]+len(keys)<=limits[kind],'本Goal累计新额度不足')
        record={'output':str(output),'request_kind':kind,'reserved_requests':len(keys),'request_keys':keys,
                'authorization_sha256':hashlib.sha256(json.dumps(authorization,sort_keys=True).encode()).hexdigest(),
                'refund_policy':'不自动退回失败/未知/未确认请求的预留'}
        with ledger.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        return record
