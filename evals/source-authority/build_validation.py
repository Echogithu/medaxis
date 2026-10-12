"""在算法修改前冻结新原文题；不从当前召回输出反推gold。"""
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
TASK=ROOT/'.ai/tasks/2026-10-08-source-authority'


def build():
    source=ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1'
    corpus=json.loads((source/'corpus.json').read_text(encoding='utf-8'))
    previous=json.loads((source/'dataset.json').read_text(encoding='utf-8'))
    docs={d['id'][:4]:d for d in corpus['documents']}
    # 全部来自原文段落，范围不与旧gold重叠；主题不含4道开发漏题。
    definitions=[
      ('0a9e','急性感染性腹泻病指','急性感染性腹泻病发','急性感染性腹泻病的定义中病程范围是多少，是否限定感染因素'),
      ('0a9e','（四）血培养','（五）其他','腹泻儿童哪些情况需要做血培养，是否包括小于三个月的婴儿'),
      ('0a9e','特别注意：严重低钠','2.高钠血症','严重低钠血症纠正时，第一天和随后每天血钠变化有什么限制'),
      ('0a9e','4.炎症性肠病','六、病情严重程度','腹泻鉴别炎症性肠病时可能有哪些肠外表现，需要怎样明确诊断'),
      ('5ce0','1.1.2 In infants','1.1.3 In children','新生儿四周以内发热时，用哪种温度计在哪个部位测量'),
      ('5ce0','1.1.3 In children','1.1.4 Healthcare','Which thermometers are recommended for children aged four weeks to five years?'),
      ('5ce0','1.2.9 Recognise','1.2.10 Measure','What does capillary refill of three seconds or longer indicate during fever assessment?'),
      ('5ce0','1.2.10 Measure','1.2.11 In children','给发热孩子量血压通常在什么情况下建议进行，还需要什么设备条件'),
      ('95b3','潜伏期一般为','（一）临床表现','流感潜伏期通常多久，一般范围是什么'),
      ('95b3','（一）传染源','（二）传播途径','流感从潜伏期到急性期是否有传染性，儿童排毒能超过一周吗'),
      ('95b3','（四）危重型','八、重型','流感危重型的判断是否包括休克以及其他器官功能衰竭'),
      ('95b3','八、重型/危重型高危人群','九、鉴别诊断','流感重型高危人群的年龄和基础疾病范围是什么，是否包括孕妇'),
      ('eb49','（五）静脉注射免疫球蛋白','（六）胸腔引流','MPP指南中IVIG治疗适用于哪些并发症或免疫反应情况'),
      ('eb49','（六）胸腔引流','（七）预防性抗凝','支原体肺炎中到大量胸腔积液是否应早期引流，通常需要外科治疗吗'),
      ('eb49','抗凝治疗：血流动力学','2.NP','支原体肺炎并肺栓塞的抗凝治疗需要怎样监测，什么条件下才能停止'),
      ('eb49','3.肺康复训练','MPP 诊疗流程图','儿童肺炎慢性气道后遗症的康复训练有哪些方式，是否需要专业指导'),
    ]
    units=[];cases=[]
    for i,(prefix,left,right,query) in enumerate(definitions,1):
        doc=docs[prefix];text=doc['content']
        if text.count(left)!=1:raise ValueError('锚点不唯一：'+left)
        a=text.index(left);b=text.index(right,a+len(left));raw=text[a:b]
        a+=len(raw)-len(raw.lstrip());quote=raw.strip();b=a+len(quote)
        if any(u['document_id']==doc['id'] and max(a,u['start'])<min(b,u['end']) for u in previous['gold_units']):raise ValueError('新旧gold重叠')
        uid=f'V{i:02d}'
        units.append({'id':uid,'topic':left,'document_id':doc['id'],'document_title':doc['title'],
          'document_sha256':doc['text_sha256'],'start':a,'end':b,'quote':quote,'qualifiers':[],
          'review_status':'ai_draft_not_clinically_reviewed','reviewer':None,'split':'validation'})
        cases.append({'id':f'H{i:02d}','topic_id':uid,'split':'validation','family':'new_evidence_topic',
          'query':query,'expected_action':'retrieve_evidence','gold_ids':[uid],'synthetic_patient_context':None,
          'review_status':'ai_draft_not_clinically_reviewed'})
    for i,query in enumerate(['成人急性心肌梗死介入手术的支架规格如何选择',
        '白内障人工晶体屈光度计算公式在这些文档哪里',
        '这批文档有没有溃疡性结肠炎长期生物制剂维持治疗的推荐',
        '流行性感冒2028年版诊疗方案新增了哪些推荐'],17):
        cases.append({'id':f'H{i:02d}','topic_id':f'V{i:02d}','split':'validation','family':'no_answer',
          'query':query,'expected_action':'no_evidence','gold_ids':[],'synthetic_patient_context':None,
          'review_status':'ai_draft_not_clinically_reviewed'})
    output=TASK/'validation-frozen-v1';output.mkdir(exist_ok=False)
    dataset={'version':'source-authority-validation-v1','scope':'同语料新主题验证；主代理构造且可见，非盲测；不得用于调参；医学及限定词专业标注待审核',
       'gold_units':units,'cases':cases,'professional_reviewed':0,'qualifier_annotations_complete':False}
    path=output/'dataset.json';path.write_text(json.dumps(dataset,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cases':20,'positive':16,'no_answer':4,
      'previous_dataset_sha256':hashlib.sha256((source/'dataset.json').read_bytes()).hexdigest(),
      'source_before_sha256':json.loads((TASK/'source-before-sha256.json').read_text(encoding='utf-8')),
      'frozen_before_algorithm_changes':True,'gold_range_overlap_with_old':False,'source_corpus_shared':True,
      'not_blind':True,'do_not_select_parameters_using_validation_results':True}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'QUESTIONS.md').write_text('# 新增20题（待专业审核，不用于调参）\n\n'+'\n'.join(f"- {c['id']}：{c['query']}" for c in cases)+'\n',encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':build()
