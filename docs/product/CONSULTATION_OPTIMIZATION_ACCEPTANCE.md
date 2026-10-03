# 问诊与引用优化验收

2026-10-03 更新。此前的预算停止及来源隐藏存在回归，已完成本地修复；具体原因、最新前后对比与真实模型记录见[回归修复报告](CONSULTATION_REGRESSION_FIX.md)。[原对比报告](CONSULTATION_OPTIMIZATION_COMPARISON.md)保留历史结果并明确纠正错误标准。未部署或修改数据库 schema。

## 验收前准备

使用隔离测试环境、测试患者账号和合成输入；确认后端已加载当前源码、前端使用当前构建。无需数据库迁移。管理员首次打开系统设置会由既有 `/admin/settings` 处理器补齐缺失的默认设置，不覆盖已有值；本轮没有替用户执行这项数据库写入。

| 设置键 | 默认值 | 运行时范围与含义 |
|---|---:|---|
| `diagnosis.interview_questions_per_round` | 1 | 1–2；每轮实际发出的卡片上限 |
| `diagnosis.interview_max_rounds` | 6 | 1–12；建议轮次，不能截断尚未询问的必要问题 |
| `diagnosis.internal_source_candidates` | 10 | 1–20；内部检索候选数 |
| `diagnosis.external_source_candidates` | 10 | 1–20；外部候选数，还受 `external_search.max_results` 限制 |
| `diagnosis.source_min_relevance` | 0.25 | 0–1；语义重排过滤阈值；词匹配降级不套用该阈值，不是医学概率 |
| `diagnosis.report_source_limit` | 10 | 1–10；报告模型可用的最终来源总上限，沿用原设置 |

问诊策略在会话开始时保存，因此调整问诊设置后应新建问诊。外部检索仍由 `external_search.enabled` 控制，关闭时不发外部请求。候选数与最终引用数不同：两类候选合并重排，过滤后按总上限截取，报告可能只引用其中一部分；没有固定内外比例或外部保留席位。

## 患者体验验收

| 场景 | 操作 | 通过标准 |
|---|---|---|
| 主诉信息复用 | 新建问诊，输入“昨晚开始头部轻微不适，未服药，药物过敏史不清楚” | 已有原话支持的起病时间、程度、用药不机械重问；“不清楚”保留为未知，不改成“无过敏” |
| 每轮数量 | 设置每轮 1，另开会话；再用每轮 2 开新会话 | 分别最多 1/2 张卡片；不是强制凑满，题目显示询问目的 |
| 未知与重复 | 一项问题回答“不清楚”，继续回答其他题 | 不因换编号或措辞再次问同一项；继续问其他必要项，未知保留在总结中 |
| 待答保护 | 出现卡片后尚未回答，在测试端重复请求下一步 | 返回等待回答，不将已发题当成已回答，不提前出信息充分的总结；自动用例覆盖该情况 |
| 建议轮次 | 测试环境将最大轮数设为 1，新建问诊并回答首轮；保留尚未询问的必要项 | 达到轮次后继续发必要题；不能用缺口列表代替补问。模型列出必要缺口却未发题时恢复生成一次，仍失败则显式报错 |
| 互补病史 | 同时提供“轻度焦虑”和“甲亢严重程度不清楚” | 两种疾病的描述不会仅因原话不同就显示“前后不一致” |
| 冲突确认 | 在自动用例中提供同维度冲突原话，并明确回答一次核对题 | 一次核对可成为当前患者自述，历史仍保留；后续新冲突重新标记待核对；未知、假设性回答不能消除冲突 |
| 继续补充 | 阶段总结点击“补充信息并追问”，输入补充内容 | 弹窗关闭、输入框获得焦点，走既有诊后追问接口；原总结保留，不自动重写，也不自动重启问诊 |
| 模型错误 | 运行生成失败的自动用例 | 错误显式返回，不通过“零题”转成信息充分 |

模型具体措辞和发问顺序可能变化。数量、状态与原话验证由程序约束；医学上是否漏问重要内容，需要单独对完整问诊及阶段总结进行专业评审。

## 引用验收

1. 用评测中的固定来源检查三种情况：可信但无关的外部来源不因可信而入选；相关外部来源可以领先内部来源；内外来源进入同一重排池。
2. 打开问诊总结的参考资料：保留全部已选取的实际来源，能看标题、内部/外部类型、原文、相关性方法与理由。正文使用的资料显示对应陈述和核对说明；未使用的资料明确标注“未作为正文引文”。没有统一评估的旧报告不展示伪造分数。
3. 点击正文 `[S1]` 等编号：应打开并聚焦同编号资料。排序只调整显示位置，不重编号。同方法、同检索主题的有效分数可排序；不把旧版或混合口径分数硬排在一起。
4. 在 1440、390、320 像素宽度查看阶段提示、长原文和引用卡片：无横向溢出，来源导航和展开原文可用。
5. 运行候选预算测试：最终 `top_k=1` 时仍能召回配置的内部 2 / 外部 3 候选，再共同筛选为 1；外部关闭时不请求外部，不生成随后被丢弃的内部摘要。
6. 打开过去只显示来源数量的历史报告：同一会话有已保存检索记录时，恢复原来源编号及原文，不能从后续追问借用资料；没有原记录时如实说明无法恢复，不编造来源。
7. 新报告遗漏正文编号时，允许一次受校验的引用补绑定：仅在现有医学陈述旁加入实际来源编号，不改正文，不把患者自述当成知识库证据。
8. 检索失败或正文不能形成有效引用时，不得生成/保存成功医学报告；当前题卡允许重试。真实检索归零修复及当前159项后端门禁见[真实链路验收](SOURCE_EMPTY_RUNTIME_FIX.md)。

相关性只评价检索主题匹配程度。原文是否支持报告结论仍沿用独立的引用证据核对；可信来源、相关来源、支持结论是三个不同判断。

## 自动验收命令

从项目根目录 `D:\CAI-Projects\medaxis` 开始。以下后端集合不调用生产数据库；不要用全量 pytest 替代，既有数据库 fixture 包含建表/清表操作。

```powershell
Set-Location D:\CAI-Projects\medaxis\backend
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short tests/test_consultation_regressions.py tests/test_source_candidate_budget.py tests/test_optimization_scorer.py tests/test_source_relevance_policy.py tests/test_interview_optimization.py tests/test_intent_latency.py tests/test_source_selection.py tests/test_knowledge_citations.py tests/test_rag_relevance.py tests/test_claim_evidence.py tests/test_clinical_context.py tests/test_patient_llm_errors.py tests/test_guest_sse_token_event.py tests/test_patient_cases.py

Set-Location ..\frontend
npm test
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json
npm run build
```

2026-10-03 结果：后端 **149 passed**；前端 **65 passed**；TypeScript 与构建 exit 0。测试集合包含既有回归，数量不是本轮新增数。构建有既有大体积 chunk 提示，不表示体积或加载性能已优化。

浏览器使用 Python + Playwright 和已安装 Edge。一个终端启动 Vite，另一个终端执行测试；API、身份、报告、追问均为测试替身，不写数据库。

```powershell
# 终端一，frontend 目录
npm run dev -- --host 127.0.0.1 --port 3011 --strictPort

# 终端二，frontend 目录
$env:CHAT_TEST_URL='http://127.0.0.1:3011'
$env:REPORT_SCREENSHOT_DIR='../.ai/tasks/2026-10-03-consultation-regressions/browser-recheck'
python tests/consultation_optimization_browser.py
$env:REPORT_SCREENSHOT_DIR='../.ai/tasks/2026-10-03-consultation-regressions/browser-existing-recheck'
python tests/report_reading_browser.py
```

通过标准：两脚本 exit 0；新脚本输出排序 `S2/S4/S3/S1/S5`、补充入口与原总结保留、零引用历史来源恢复及内部标识不泄露 PASS；旧脚本报告阅读回归 PASS。测试中来源分数是合成值，不证明真实知识库的排序质量。

## 恢复与验收记录

工作区存在大量其他未提交修改。本次修复的局部恢复点为 `.ai/tasks/2026-10-03-consultation-regressions/baseline/` 与 `baseline-manifest.json`；原 2026-10-02 快照也保留。恢复时只比较并撤销本次问诊/引用差异，保留其他修改；没有旧文件快照的改动逐段核对，不整仓 reset 或整目录覆盖。新增评测和文档可以先保留；需要移除时按可恢复操作处理。

若在测试环境修改了设置，记录原值并恢复原值；本轮未修改运行中的数据库设置。验收表记录输入、输出、是否重复、卡片数、缺口、来源编号及截图。真实患者、真实知识库、完整多轮模型质量和临床充分性不在本轮自动验收证据内。
