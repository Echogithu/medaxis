"""从已核验结果生成用户可读对照；保留失败，不把覆盖率当医学准确率。"""
import argparse
from pathlib import Path
from verify import ROOT,read,verify


def main(output):
    result=verify(output)
    dataset=read(ROOT/'.ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json')
    profiles=list(result['profiles'])
    groups=result['groups']
    percent=lambda n:f'{n*100:.1f}%'
    lines=['# 元信息上下文补充：第四阶段实验对照','',
        '**结论：有完整证据覆盖收益，但上线门禁未满足，未接入问诊。**','',
        '本轮复用阶段3实际PostgreSQL检索的chunk ID；以下质量成绩是冻结召回的离线三组重放，不是新的数据库检索、问诊报告或临床效果。45题含40正例、5无答案草稿；验收题成绩已公开，非盲测；专业核对数仍为0。','',
        '实验只调整内部摘录选取与预算，来源条数、原文、题库、量尺v2和来源排序算法保持一致。每条最多1600字符、邻接最多前后各300字符、只取同文档index±1、保留整个锚点；无法唯一定位时回退。上下文选取不读gold，也不用query挑位置。','',
        '| 指标 | 原路径800 | 原路径1600 | 邻接上下文1600 |','|---|---:|---:|---:|']
    for key,label in [('complete_evidence_rate','完整证据覆盖'),('qualifier_recall','限定条件覆盖'),('hit_at_k','证据命中'),('unsupported_candidate_rate','无答案仍返回候选（越低越好）')]:
        lines.append('| '+label+' | '+' | '.join(percent(groups[p]['summary'][key]) for p in profiles)+' |')
    lines.append('| 首个证据MRR | '+' | '.join(f"{groups[p]['summary']['mrr']:.4f}" for p in profiles)+' |')
    lines.append('| 45题所选来源总字符 | '+' | '.join(str(groups[p]['source_chars']) for p in profiles)+' |')
    lines+=['', '字数控制组单独增加预算没有提高完整覆盖（32/40保持32/40）；同1600上限补相邻内容提高到36/40。改善R08/R21/R23/R40，覆盖/限定条件回退为0题。', '',
        '代价：相对原路径800，来源总文本293680→607210字符，约增106.8%；同1600控制组比，增加约62.4%。字符量只作输入规模代理，本轮没有新模型调用，不能宣称真实token、费用或端到端延迟降低。', '',
        '门禁失败：R42从无候选变成候选（增预算组1条、补上下文组2条），5个无答案题的候选返回由4/5增至5/5。这个变化在字数控制组已经出现。原关键词降级规则可因少量泛词命中保留来源；本题新增来源的词覆盖分数仅0.0556。这是检索层风险，未执行报告生成，不能等同已发生误诊。', '',
        '排序代价：相对800基线R10首证据排名下降；相对1600控制组R10/R22下降，字数控制组相对800还有R24下降。未按验收结果调margin/阈值，不把它们藏在平均MRR收益里。', '',
        '第一轮失败也保留：query窗口800开发集完整覆盖75%→62.5%，R03/R22/R24/R38回退，未接入。结果及源码在development-v1/；第二轮开发集development-v2/，完整集full-v2/，边界防御及硬预算校验后的最终记录full-final/。', '',
        '## 当前元信息与缺口','',
        'Document已有id/title/source_type/source_url；DocumentChunk已有id/document_id/chunk_index。本轮通过唯一原文匹配生成start/end、参与chunk_ids和source_text_sha256，不迁移schema、不重建向量。新定位器仅是实验候选，问诊工具没有调用它，引用序号/来源ID/默认800预算保持现状。', '',
        'metadata-verified/：本地Docker测试PostgreSQL只读核对4文档/125chunk，与冻结原文及片段内容一致；每个定位窗口核对原文坐标、完整锚点和预算，回退状态逐chunk留存。不是新检索评测；api_feature_enabled为null，未读取API功能运行状态。', '',
        '4篇文档source_url都为空。官方URL、发布机构、明确版本、发布日期、章节和页码需要原始材料/人工核验，不能由邻接算法猜填。updated_at是平台更新时间，不能冒充官方发布日期。', '',
        '## 逐题验收对照','',
        '| ID | 划分 | 800完整覆盖 | 1600完整覆盖 | 上下文完整覆盖 | 800→上下文MRR | 候选条数（三组） |','|---|---|---:|---:|---:|---|---|']
    rows={p:{r['id']:r for r in groups[p]['cases']} for p in profiles}
    for cid in result['prefix_parity_ids']:
        selected=[rows[p][cid] for p in profiles]
        case=next(c for c in dataset['cases'] if c['id']==cid)
        coverage=['无答案' if r['score']['complete_evidence'] is None else str(int(r['score']['complete_evidence'])) for r in selected]
        mrr=f"{selected[0]['score']['mrr']}→{selected[2]['score']['mrr']}"
        counts='/'.join(str(len(r['sources'])) for r in selected)
        lines.append(f"| {cid} | {case['split']} | {' | '.join(coverage)} | {mrr} | {counts} |")
    lines+=['', '原始证据：full-final/results.json的groups各组cases.sources为真实连续原文摘录和文档坐标；context_metadata记录命中锚点、参与chunk和原文hash。题目/金标原文见阶段2frozen-v1/QUESTIONS.md及GOLD_REVIEW.md。', '',
        '## 下一步','',
        '先在开发集单独验证相关性筛选，覆盖泛词偶然命中、错误主题、否定/条件与跨语言正例；固定规则后再用新增未看过样本验收。保留当前45题作为回归，不能重新包装成盲测。达到覆盖/限定条件不退、无答案候选不增后，再接入问诊并验证元信息在来源归一化、报告保存和引用展示中的保留。', '',
        '阶段4实际检索前后45题、报告生成和页面验收尚未执行；目前不重启后端、不扩大到这些路径。演示保护false，limit20/used19；runtime-final.json健康200，provider_calls0。', '']
    target=output.parent/'REPORT.md'
    target.write_text('\n'.join(lines),encoding='utf-8')
    print('REPORT:',target)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    main(parser.parse_args().output)
