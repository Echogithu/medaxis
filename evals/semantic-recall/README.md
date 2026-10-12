# 第三阶段：独立语义召回与同题对照

查看结果及验收以[阶段验收页](../../docs/product/SEMANTIC_RECALL_ACCEPTANCE.md)为准。本工具使用第二阶段冻结的4份平台指南、125片段、45题和真实查询向量，不调用诊断模型，不读患者。

`score_v2.py`仅允许原文覆盖中的纯空白缺口；数字、否定、正文和标点仍必须覆盖。v1保持原样；旧输出R19的量尺校准不算检索提升。

## 无费用复算

在MedAxis根目录运行，不需要启动Docker：

```powershell
python -m unittest discover -s evals/semantic-recall -p 'test_*.py' -v
python evals/semantic-recall/verify_stage3.py --task .ai/tasks/2026-10-08-semantic-recall --baseline .ai/tasks/2026-10-07-rag-baseline
```

预期10项测试OK，校验输出`verified_stage3`、database_cases=45、calibration_only_ids=[R19]、improved_ids=[R12,R14,R16,R18]，覆盖/排名退步为空，9类反例全部被拒绝。退出码0证明归档可复算；专业gold未核对，不等于医学准确率。`.ai`快照是本机资料，不随公开克隆分发。

## 实际PostgreSQL复跑

Docker后端须可用，指南、配置和非实验模块源码须与冻结快照一致，没有启用重排供应商。脚本在独立Python进程加载明确归档的RAG源码，执行只读事务并回滚；不会替换正在运行的HTTP API。模型HTTP被阻断，复用已有45条真实向量。任何额外网络尝试均判失败；不要绕过这个检查。

输出目录必须是新目录。先跑代表题，再运行完整题集：

```powershell
python evals/semantic-recall/run.py run --baseline .ai/tasks/2026-10-07-rag-baseline --rag-source backend/app/services/rag.py --label smoke --ids R01,R12,R16,R32,R42 --output .ai/tasks/2026-10-08-semantic-recall/recheck-smoke
python evals/semantic-recall/run.py run --baseline .ai/tasks/2026-10-07-rag-baseline --rag-source backend/app/services/rag.py --label full --output .ai/tasks/2026-10-08-semantic-recall/recheck-full
python evals/semantic-recall/run.py compare --baseline .ai/tasks/2026-10-07-rag-baseline --before .ai/tasks/2026-10-08-semantic-recall/before-v2 --after .ai/tasks/2026-10-08-semantic-recall/recheck-full --output .ai/tasks/2026-10-08-semantic-recall/recheck-comparison
```

`--split development`用于开发集；不能同时指定`--ids`与`--split`。比较要求相同题目集合、原文、查询向量、来源预算及量尺/严格评分依赖。执行器、源码、来源原文坐标、分组/阶段/汇总成绩逐项复算。缺题、失败、超额/重复来源和被篡改原文不允许冒充完整运行。

`results.json`包含逐题关键词候选、内部语义排序结果、最终来源与原文坐标。`coarse`阶段仍表示关键词候选；独立语义的增益在`internal`阶段出现。`executor/rag.py`是实际执行源码，`source_sha256`是当时挂载文件指纹，两者职责不同。早期RRF和并集试验的mode标签沿用`postgres_same_inputs_rrf_experiment`，最终封存已改为通用`postgres_same_inputs_retrieval_experiment`，不得只凭标签判断算法。

`provider_usage`追溯第二阶段生成查询向量的1,278 tokens，不是本轮新增费用。本轮额外模型网络=0。计时包含缓存向量检索，排除向量生成/诊断报告；P95使用nearest-rank，不能当作生产端到端延迟。

## 运行态只读检查

```powershell
python evals/semantic-recall/inspect_runtime.py --output .ai/tasks/2026-10-08-semantic-recall/runtime-recheck.json
```

仅读取enabled/limit/used、健康HTTP状态和挂载RAG文件指纹。它不能证明HTTP进程已加载新源码，也不写设置。用户已要求保持演示保护关闭，本工具不会自动恢复。
