"""从冻结原文建立检索证据草稿；不读取检索输出，也不生成医学答案。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_dataset(corpus, spec, snapshot_id):
    documents=corpus['documents']
    units=[]
    cases=[]
    for i,t in enumerate(spec['topics']):
        doc=documents[t['doc']]
        content=doc['content']
        if content.count(t['start'])!=1:
            raise ValueError(f"起点必须唯一：{t['topic']}")
        start=content.index(t['start'])
        end=content.find(t['end'],start+len(t['start']))
        if end<0:
            raise ValueError(f"终点不存在：{t['topic']}：{t['end']}")
        quote=content[start:end].rstrip()
        end=start+len(quote)
        qualifiers=[]
        for value in t['qualifiers']:
            pos=quote.find(value)
            if pos<0:
                raise ValueError(f"限定词不在原文范围：{t['topic']}：{value}")
            qualifiers.append({'text':value,'start':start+pos,'end':start+pos+len(value)})
        uid=f'E{i+1:02d}'
        split='evaluation' if i%5 in (2,4) else 'development'
        unit={'id':uid,'topic':t['topic'],'document_id':doc['id'],'document_title':doc['title'],
              'document_sha256':doc['text_sha256'],'start':start,'end':end,'quote':quote,
              'qualifiers':qualifiers,'review_status':'ai_draft_not_clinically_reviewed','reviewer':None,
              'split':split,'original_url_status':'missing' if not doc['source_url'] else 'not_verified'}
        units.append(unit)
        for j,query in enumerate(t['queries']):
            family='exact_terms' if j==0 else 'cross_language' if t['doc']==1 else 'paraphrase'
            cases.append({'id':f'R{i*2+j+1:02d}','topic_id':uid,'split':split,'family':family,'query':query,
                          'expected_action':'retrieve_evidence','gold_ids':[uid],
                          'synthetic_patient_context':None,'review_status':unit['review_status']})
    all_text='\n'.join(d['content'] for d in documents)
    for i,t in enumerate(spec['no_answer']):
        if any(v in all_text for v in t['absent_terms']):
            raise ValueError('无答案草稿的缺失词实际存在，需核对')
        cases.append({'id':f'R{len(cases)+1:02d}','topic_id':f'N{i+1:02d}',
                      'split':'evaluation' if i in (1,3) else 'development', 'family':'no_answer',
                      'query':t['query'],'expected_action':'no_evidence','gold_ids':[],
                      'absence_checks':t['absent_terms'],'review_status':'ai_draft_not_clinically_reviewed',
                      'absence_scope':'词条在这份有限快照中未出现；尚未由专业人员确认无可替代证据'})
    return {'id':'medaxis-rag-grounded-draft-v1','version':1,'snapshot_sha256':snapshot_id,
            'annotation_status':'ai_draft_not_clinically_reviewed','clinical_metrics_allowed':False,
            'gold_units':units,'cases':cases}


def validate(corpus,dataset):
    docs={d['id']:d for d in corpus['documents']}
    units={u['id']:u for u in dataset['gold_units']}
    if not docs or len(docs)!=len(corpus['documents']) or not units or len(units)!=len(dataset['gold_units']):
        raise ValueError('文档或证据单元为空、重复')
    ids=[c['id'] for c in dataset['cases']]
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('题目为空或重复')
    for unit in units.values():
        doc=docs[unit['document_id']]
        if not 0<=unit['start']<unit['end']<=len(doc['content']) or hashlib.sha256(doc['content'].encode()).hexdigest()!=unit['document_sha256'] or doc['content'][unit['start']:unit['end']]!=unit['quote']:
            raise ValueError('gold原文或坐标不一致')
        for q in unit['qualifiers']:
            if not unit['start']<=q['start']<q['end']<=unit['end'] or doc['content'][q['start']:q['end']]!=q['text']:
                raise ValueError('限定条件坐标不一致')
    splits={}
    for c in dataset['cases']:
        if c['split'] not in ('development','evaluation') or c['expected_action'] not in ('retrieve_evidence','no_evidence'):
            raise ValueError('题目划分或预期动作无效')
        if not c['query'].strip() or len(c['gold_ids'])!=len(set(c['gold_ids'])) or any(uid not in units for uid in c['gold_ids']):
            raise ValueError('题目查询或gold引用无效')
        for uid in c['gold_ids']:
            if units[uid]['split']!=c['split']:
                raise ValueError('同一证据泄漏到另一划分')
        if c['topic_id'] in splits and splits[c['topic_id']]!=c['split']:
            raise ValueError('同主题改写跨集合泄漏')
        splits[c['topic_id']]=c['split']
        if (c['expected_action']=='no_evidence') != (not c['gold_ids']):
            raise ValueError('无答案题与gold不一致')
    return {'cases':len(ids),'units':len(units),'development':sum(c['split']=='development' for c in dataset['cases']),
            'evaluation':sum(c['split']=='evaluation' for c in dataset['cases']), 'clinical_reviewed':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    corpus=read(args.corpus)
    dataset=make_dataset(corpus,read(HERE/'topics.json'),digest(args.corpus))
    summary=validate(corpus,dataset)
    for name,sha in corpus['source_sha256'].items():
        if digest(ROOT/'backend'/name)!=sha:
            raise ValueError('运行容器与本地源码不同，不能混用')
    args.output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(args.corpus,args.output/'corpus.json')
    for name in corpus['source_sha256']:
        target=args.output/'source'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'backend'/name,target)
    for name in ('dataset.json','validation.json'):
        value=dataset if name=='dataset.json' else summary
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    table=['# 测试题清单','', '状态：45条草稿；全部待专业核对，不能用于临床准确率。','',
           '| ID | 划分 | 类型 | 查询 | gold |','|---|---|---|---|---|']
    table += [f"| {c['id']} | {c['split']} | {c['family']} | {c['query']} | {','.join(c['gold_ids'])} |" for c in dataset['cases']]
    (args.output/'QUESTIONS.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
    review=['# 原文证据草稿核对','', 'AI草稿；位置已机械核对，医学支持、适用性和无答案判定未专业核对。不要根据检索结果改gold。','']
    for u in dataset['gold_units']:
        review += [f"## {u['id']} {u['topic']}",'',f"文档：{u['document_title']}；字符范围 [{u['start']}, {u['end']})。",'',
                   '```text',u['quote'],'```','',f"候选限定条件：{', '.join(q['text'] for q in u['qualifiers'])}",'',
                   '- [ ] 查询与这段原文对应；必要条件未遗漏', '- [ ] 版本与官方出处已核对', '- [ ] 记录核对者、日期及是否需要修订新版本','']
    review += ['## 无答案草稿','', *[f"- {c['id']}：{c['query']}；须核对全快照是否存在替代证据。" for c in dataset['cases'] if not c['gold_ids']]]
    (args.output/'GOLD_REVIEW.md').write_text('\n'.join(review)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
