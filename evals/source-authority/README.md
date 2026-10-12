# 阶段6：官方出处与候选保护评测

先看[对比报告](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-08-source-authority/REPORT.md)和[验收说明](D:/CAI-Projects/medaxis/docs/product/SOURCE_AUTHORITY_ACCEPTANCE.md)。实验材料在`.ai/tasks/2026-10-08-source-authority/`，不随Git自动分发；脚本本身不能替代语料、向量、源码快照及真实结果。

## 无模型费用的结果复核

在项目根目录PowerShell执行：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/source-authority/verify.py .ai/tasks/2026-10-08-source-authority/old45-final --dataset .ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json --corpus .ai/tasks/2026-10-08-source-authority/post-url-snapshot/results.json --embeddings .ai/tasks/2026-10-07-rag-baseline/query-embeddings.json
backend/.venv/Scripts/python.exe -X utf8 evals/source-authority/verify.py .ai/tasks/2026-10-08-source-authority/validation20-final --dataset .ai/tasks/2026-10-08-source-authority/validation-frozen-v1/dataset.json --corpus .ai/tasks/2026-10-08-source-authority/post-url-snapshot/results.json --embeddings .ai/tasks/2026-10-08-source-authority/validation-vectors/results.json
backend/.venv/Scripts/python.exe -X utf8 evals/source-authority/test_verify.py
backend/.venv/Scripts/python.exe -X utf8 evals/source-authority/test_curation.py
```

应为exit0、45题PASS、20题PASS、9项和6项OK。复核器会重算逐题成绩、原文范围、上下文来源、真实余弦值与URL，同时检查输入及源码指纹；8种损坏反例应被拒绝。新增题限定词未专业标注，限定词指标为null。

## 复跑实际检索

`runner.py evaluate`在`medaxis-backend`中新启Python进程，走真实问诊检索工具和PostgreSQL；缓存真实向量、阻断额外HTTP、只读事务结束rollback。它不证明常驻HTTP进程已载入代码。源码、语料、策略漂移，或启用真实reranking供应商时拒绝执行。

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/source-authority/runner.py evaluate --corpus .ai/tasks/2026-10-08-source-authority/post-url-snapshot/results.json --dataset .ai/tasks/2026-10-07-rag-baseline/frozen-v1/dataset.json --embeddings .ai/tasks/2026-10-07-rag-baseline/query-embeddings.json --output .ai/tasks/2026-10-08-source-authority/old45-rerun
```

输出目录必须全新，拒绝覆盖记录。新20题只在算法冻结后做了一次验证；复核不等于调参。它已暴露，未来若根据H17/H18/H19修复，必须另建事前冻结验证集，不继续称这20题独立验证。

## 官方链接补录

`curate.py`默认dry-run，需要官方PDF、提取文本、核验清单、原始快照；`--apply`才写库。4条URL已经提交，**不要再次运行apply**；旧值检查会拒绝重复执行。`url-dry-run/plan.json`和`url-apply/database/results.json`保存具体ID、旧空值、新URL、内容哈希与事务证据。只更新`source_url`，`updated_at`等其它字段也未改。全知识库162个chunk不变，评测其中125个平台指南chunk。

`source-authority-manifest.json`是补录前的冻结核验清单，其`database_updated:false`是当时状态；当前提交状态见`source-authority-status.json`及真实apply/提交后快照，不改写历史清单。发行机构/日期/版次保存在核验清单中，未新增数据库字段或界面字段。2020附件确切发布日期未证实，保持null；NICE版权年份不当作发布日期。

## 代码测试

后端目录：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_rag_keyword_reserve.py tests/test_source_filter_gate.py tests/test_source_context_integration.py tests/test_rag_context.py tests/test_rag_context_budget.py tests/test_knowledge_citations.py tests/test_source_candidate_budget.py tests/test_rag_relevance.py tests/test_source_relevance_policy.py tests/test_source_empty_runtime.py -q -p no:cacheprovider
```

前端目录：

```powershell
node --experimental-strip-types --test tests/reportCitations.test.mjs tests/reportLifecycle.test.mjs tests/reportLinks.test.mjs
```

本轮82项、13项通过；未改前端生产代码，无新增构建或依赖。本轮不是全仓测试、完整报告生成或医学安全认证。

## 恢复

代码恢复点`source-before/rag.py`。对照快照只撤新增`_reserve_keyword_candidate`及search中的调用，保留之前的引用/上下文修复和其它脏改动；不要整仓reset或整文件覆盖。URL恢复由操作者明确决定后执行：以apply回执中4个ID和新URL作为条件，事务内参数化更新`source_url`为记录的旧值null，核对恰好4行、正文及chunk指纹不变才提交；条件不符停止，不自动覆盖。不是日常验收步骤，不由评测脚本自动恢复。
