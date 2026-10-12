"""用已归档真实结果证明复核器会拒绝损坏记录；不运行数据库/供应商。"""
import json
import shutil
from pathlib import Path

import pytest
from verify import ROOT,verify


@pytest.fixture
def archived(tmp_path):
    source=ROOT/'.ai/tasks/2026-10-08-source-filter/postgres-final'
    if not source.exists():
        pytest.fail('先按README生成postgres-final实际只读归档')
    shutil.copytree(source,tmp_path/'archive')
    return tmp_path/'archive'


def test_valid_archive_is_verified(archived):
    assert len(verify(archived)['requested_ids'])==45


@pytest.mark.parametrize('damage',['missing_group','missing_case','fake_score','wrong_saved_excerpt','wrong_fingerprint','wrong_summary','wrong_context'])
def test_corrupted_result_is_rejected(archived,damage):
    path=archived/'results.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    group=data['groups']['after']
    row=next(r for r in group['cases'] if r['serialized_sources'])
    item=row['serialized_sources'][0]
    if damage=='missing_group':data['groups'].pop('after')
    elif damage=='missing_case':group['cases'].pop()
    elif damage=='fake_score':item['retrieval_score']=.999999
    elif damage=='wrong_saved_excerpt':item['excerpt']='伪造摘录'
    elif damage=='wrong_fingerprint':item['retrieval_query_fingerprint']='other-query'
    elif damage=='wrong_summary':group['summary']['complete_evidence_rate']=1.0
    elif damage=='wrong_context':item['context_metadata']['start']+=1
    path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    with pytest.raises(ValueError):verify(archived)
