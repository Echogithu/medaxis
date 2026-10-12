# 来源筛选和上下文补充对照

阶段5复用冻结语料、题库、查询向量和原文量尺；不改变患者、schema、额度、依赖或演示保护。`replay.py`是离线实验，`run_postgres.py`在Docker实际调用问诊检索工具；两者不等于运行中的HTTP服务或完整报告验收。实际入口调用是只读事务，禁新增HTTP，外部搜索显式排除。

固定输入位于`.ai/tasks/2026-10-07-rag-baseline/frozen-v1/`，查询向量在其父目录；旧路径来源在阶段3`union-final-v2`、阶段4`full-final`和阶段5`source-before`。这些是本机实验材料，需一并保留，只有脚本的Git副本不能独立重现历史实验。先看[用户验收说明](D:/CAI-Projects/medaxis/docs/product/SOURCE_FILTER_ACCEPTANCE.md)。

## 已有结果复核（无数据库、模型调用）

项目根目录PowerShell：

```powershell
# 仅为本地只读脚本加载Settings的测试值，不修改容器配置。
$env:API_KEY_MASTER_KEY='test-master-key-32bytes-long!!!'
$env:SECRET_KEY='test-secret-key-32bytes-long!!!'
$env:PYTHONIOENCODING='utf-8'
backend/.venv/Scripts/python.exe evals/source-filter/verify.py .ai/tasks/2026-10-08-source-filter/postgres-final

# 首次默认临时目录被系统权限拒绝，改用新建的工作区临时目录。
$env:TMPDIR=(New-Item -ItemType Directory -Path ('.ai/tasks/2026-10-08-source-filter/verifier-temp-'+[guid]::NewGuid().ToString())).FullName
backend/.venv/Scripts/python.exe -m pytest evals/source-filter/test_verify.py -q -p no:cacheprovider
```

预期exit0、45题PASS、8 passed。反例会检查：缺对照组、缺题、假语义分、保存摘录不一致、错query指纹、错误汇总、错误上下文坐标。该测试依赖已保存的`postgres-final`，没有材料则明确失败。

## 重新运行对照

使用**新的**输出目录；脚本拒绝覆盖已有记录。容器名已验证为`medaxis-backend`。以下均从项目根目录运行，上面的脚本测试环境仍需设置：

```powershell
backend/.venv/Scripts/python.exe evals/source-filter/replay.py --output .ai/tasks/2026-10-08-source-filter/offline-rerun
backend/.venv/Scripts/python.exe evals/source-filter/run_postgres.py --offline .ai/tasks/2026-10-08-source-filter/offline-rerun --output .ai/tasks/2026-10-08-source-filter/postgres-rerun
backend/.venv/Scripts/python.exe evals/source-filter/verify.py .ai/tasks/2026-10-08-source-filter/postgres-rerun
backend/.venv/Scripts/python.exe evals/source-filter/run_cases.py --output .ai/tasks/2026-10-08-source-filter/cases-rerun
```

实际数据库、源码或配置与冻结范围不同会拒绝比较，不自动修改环境。纯内部、无reranking供应商是这次真实对照的边界。来源策略`source_gate_v2`门槛0.42只校准`text-embedding-3-small`/1536，同模型真实锚点分与同query指纹齐全才使用；不同模型、坏元信息或纯关键词不能冒充已完成语义筛选。有效统一reranker优先。邻接文字不能补救原锚点无关。

`cases.json`12题分数均是人工合成输入。首次11/12，F01暴露分类泛词漏洞；补齐“专题”分类泛词后12/12，阈值/问题/期望没有改，但样本已参与修复，因此是开发回归，不能称独立评测。原失败留在`new-cases`，修复后另存`new-cases-v2`。

## 代码回归

后端目录执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_source_filter_gate.py tests/test_source_context_integration.py tests/test_rag_context.py tests/test_rag_context_budget.py tests/test_knowledge_citations.py tests/test_source_candidate_budget.py tests/test_rag_relevance.py tests/test_source_relevance_policy.py tests/test_source_empty_runtime.py -q
```

前端目录执行：

```powershell
node --experimental-strip-types --test tests/reportCitations.test.mjs tests/reportLifecycle.test.mjs tests/reportLinks.test.mjs
npm run build
```

本轮为76 passed、13 passed、构建exit0。pytest缓存目录写入警告及Vite产物超过500kB警告不改变通过结果；本阶段未处理它们。不是全仓测试或全局类型检查。
