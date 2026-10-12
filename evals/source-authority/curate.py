"""只补已核验的4个来源URL；默认dry-run，拒绝正文漂移与重复执行。"""
import argparse
import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from runner import ROOT,TASK,execute,digest,read

EXPECTED={'0a9eb4c3-b646-4019-baea-501865133a51','5ce0452a-f1c8-41ba-bfad-326c07336560',
          '95b3f4e9-004e-419d-b916-0dd791ac2857','eb495984-b2e2-496d-8931-832fd6c9851b'}


def validate(manifest,corpus,files):
    rows=manifest['documents'];docs={d['id']:d for d in corpus['documents']}
    if len(rows)!=4 or {r['document_id'] for r in rows}!=EXPECTED:raise ValueError('仅允许4个唯一文档')
    plan=[]
    for r in rows:
        key=str(uuid.UUID(r['document_id']));doc=docs[key];url=r['new_source_url'];parsed=urlsplit(url)
        if (parsed.scheme!='https' or parsed.hostname not in {'www.nhc.gov.cn','www.nice.org.uk'}
            or parsed.username or parsed.password or parsed.port not in (None,443) or len(url)>1000
            or r['old_source_url'] is not None or r['http_status']!=200 or not r['whitespace_normalized_equal']):
            raise ValueError('来源或旧值不符合核验约束')
        if (doc['title']!=r['title'] or doc['source_url']!=r['old_source_url']
            or hashlib.sha256(doc['content'].encode()).hexdigest()!=r['local_text_sha256']):raise ValueError('文档漂移')
        pdf=files/(key+'.pdf');txt=files/(key+'.txt')
        extracted=txt.read_text(encoding='utf-8')
        # 下载记录的text_sha256是提取文本的UTF-8哈希，Windows保存时可能变成CRLF。
        if digest(pdf)!=r['pdf_sha256'] or hashlib.sha256(extracted.encode()).hexdigest()!=r['text_sha256']:raise ValueError('官方文件哈希不同')
        if re.sub(r'\s+','',extracted)!=re.sub(r'\s+','',doc['content']):raise ValueError('全文不同')
        plan.append({'document_id':key,'title':r['title'],'old_source_url':None,'new_source_url':url,
                     'content_sha256':r['local_text_sha256']})
    return sorted(plan,key=lambda r:r['document_id'])


def main(args):
    manifest=TASK/'source-authority-manifest.json';baseline=TASK/'initial-snapshot/results.json'
    plan=validate(read(manifest),read(baseline),TASK/'official-downloads')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'manifest.json').write_bytes(manifest.read_bytes())
    (args.output/'plan.json').write_text(json.dumps({'apply_requested':args.apply,'manifest_sha256':digest(manifest),
        'baseline_sha256':digest(baseline),'changed_fields':['source_url'],'rows':plan},ensure_ascii=False,indent=2),encoding='utf-8')
    encoded=base64.b64encode(json.dumps({'apply':args.apply,'rows':plan},ensure_ascii=False).encode()).decode()
    result=execute(f'p=json.loads(base64.b64decode({encoded!r}))\nprint(json.dumps(asyncio.run(sys.modules["curate_db"].run(p)),ensure_ascii=False))\n',
        args.output/'database',[('curate_db',Path(__file__).with_name('curate_db.py'))])
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--output',required=True,type=Path)
    main(p.parse_args())
