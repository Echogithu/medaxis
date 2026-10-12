# 元信息上下文阶段：查看与验收

阶段4结论（保留历史）：定位候选及离线对照已验证，当时因无答案候选回退未接入问诊。**阶段5已加来源筛选并接入本地问诊检索代码，实际工具45题只读对照通过；运行服务加载与页面验收仍待完成**，请从[阶段5验收入口](D:/CAI-Projects/medaxis/docs/product/SOURCE_FILTER_ACCEPTANCE.md)查看当前状态。本页下文仍描述阶段4实验，旧失败记录和数字不改写。

## 查看入口

- `.ai/tasks/2026-10-08-rag-context/REPORT.md`：三组指标、字数代价、改善与回退题、未完成项。
- 同目录`full-final/results.json`：45题逐题来源原文、坐标、参与chunk元信息和量尺结果。
- 同目录`development-v1/`：第一轮失败结果及源码；`development-v2/`：第二轮开发集；`full-v2/`与`full-final/`：完整回归及边界防御后的最终复跑。
- 同目录`metadata-verified/`：真实Docker/PostgreSQL只读核对4篇文档/125个chunk，含缺失出处与定位状态。
- 同目录`verification-final.json`：本轮命令、退出码、输出与代码指纹；`review.md`：挑剔自审及限制。
- `.ai/tasks/2026-10-07-rag-baseline/frozen-v1/QUESTIONS.md`、`GOLD_REVIEW.md`：冻结查询与原文证据草稿，尚未专业核对。
- `D:/AI-Command-Center/docs/commander/task-traces/2026-10-08-rag-context/CHECKPOINTS.md`：各阶段动作、证据、结论与下一步。

## 自动验收

在项目根目录运行`evals/rag-context/README.md`里的复核命令。应显示45题原文/评分复核PASS，验收器反例5 tests OK。PASS证明记录一致，**不等于上线门禁通过**。

窗口/来源预算测试：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_rag_context.py backend/tests/test_rag_context_budget.py backend/tests/test_knowledge_citations.py backend/tests/test_source_candidate_budget.py backend/tests/test_rag_relevance.py -q -p no:cacheprovider
```

本轮预期38 passed；覆盖唯一定位、重复定位回退、同文档邻接、缺口不跨越、完整锚点、负margin、超长锚点、来源ID保留、默认800及外部800硬限制。

## 手工核验

1. 看REPORT.md的三组完整证据覆盖：800→1600控制组不变，邻接组改善，收益归因不得混写。
2. 在results.json找R08/R21/R23/R40，按每个source的document_id与[start,end)回到冻结corpus.json原文，应逐字一致；查看anchor_chunk_id/chunk_ids，不把多片段内容冒充单一chunk原文。
3. 找R42：原800无来源、1600控制组1条、上下文组2条，应保留“回退”判定。再看R10/R22/R24的排名变化。
4. 看metadata-verified：缺官方URL的4篇均应保持缺失，不出现猜造发布机构、官方发布日期、章节或页码。
5. 当前页面仍走原问诊路径。不要用刷新页面来验收这项尚未接入的候选；后续必须先通过筛选门禁，再验证来源字段从工具到报告保存、历史恢复和UI均保留。

## 接入前门禁与恢复边界

同题同量尺覆盖/限定条件不退、无答案候选不增；增加摘录预算的费用/文本量独立记录；禁止用更多字符掩盖不相关信息。当前R42未满足，实际数据库检索45题/报告生成/页面引用不在本次已验证范围。

`source-before/`保存阶段4开始前rag.py、medical.py、knowledge_citations.py；未改问诊工具、RAG召回或数据库schema。不要reset整个脏工作区。若需要撤掉实验，只移除本轮新定位器/实验文件及引用归一化函数的可选预算参数，不动其他阶段；先与快照做定向diff，文件删除按项目回收站规则执行。

演示保护按用户要求保持关闭，未改额度、未新增模型调用、未重启后端。专业金标与官方出处核验仍需人工。
