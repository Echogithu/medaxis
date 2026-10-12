# 真实语料RAG题库与基线

第二阶段先建立可重复的量尺，再改检索算法。当前45题/20原文证据单元是AI草稿，专业核对为0；不是临床测试集定稿。阶段状态与本机产物见[验收入口](../../docs/product/RAG_BASELINE_ACCEPTANCE.md)。仅包含平台指南与合成问题，不读取患者。

## 已有文件与边界

| 文件 | 用途 |
|---|---|
| collect.py | 在现有后端容器只读导出平台指南、片段/向量、非敏感配置与源码哈希；另提供受演示保护约束的批量真实查询向量入口 |
| topics.json / build.py | 从原文独立建立证据范围、限定条件、题目与分组，冻结应用源码，拒绝覆盖已有输出 |
| score.py / test_score.py | 区分部分命中、完整证据覆盖、限定条件、无答案候选；反例测试拒绝重复/缺失/伪造结果 |
| replay.py | 对冻结语料SQLite副本运行冻结原RAG源码及其SQL。无查询向量时明确进入关键词降级诊断；不访问真实数据库或网络 |
| verify.py | 复算逐题和汇总分数，核对数据/源码/执行器指纹；只校验，不执行归档源码 |
| temporary.py / test_temporary.py | 本次明确授权下切换保护并在finally恢复；隔离假数据库测试成功/失败/并发冲突/恢复失败路径 |
| postgres.py / run_postgres.py | 实际PostgreSQL只读原检索服务，使用已取得的真实向量，禁止额外网络调用；保存各阶段分数 |
| verify_stage2b.py | 核对本次切换/独立恢复记录、真实向量、数据库基线和45题副本一致性 |

没有新增依赖或测试框架。量尺/构建/校验使用标准库；重放使用项目后端已有依赖，在 `backend/.venv/Scripts/python.exe` 下运行。实际环境版本保存在每次结果的 `environment`。

## 复跑与查看

在MedAxis根目录PowerShell运行。以下前两条仅校验本阶段现有材料，没有模型费用、数据库写入或服务重启：

```powershell
python -m unittest discover -s evals/rag-baseline -p test_score.py -v
python evals/rag-baseline/verify.py --frozen .ai/tasks/2026-10-07-rag-baseline/frozen-v1 --output .ai/tasks/2026-10-07-rag-baseline/keyword-full-recorded-v2
```

当前记录应显示9项测试OK，校验 `verified_artifact`、题库45/证据20/开发27/验收18，运行45题。医学核对仍为pending，在线基线仍为false。

重放写**新目录**，已有目录拒绝覆盖。先冒烟，再全量：

```powershell
backend/.venv/Scripts/python.exe evals/rag-baseline/replay.py --frozen .ai/tasks/2026-10-07-rag-baseline/frozen-v1 --output .ai/tasks/2026-10-07-rag-baseline/manual-smoke-001 --ids R01,R06,R11,R20,R43
backend/.venv/Scripts/python.exe evals/rag-baseline/replay.py --frozen .ai/tasks/2026-10-07-rag-baseline/frozen-v1 --output .ai/tasks/2026-10-07-rag-baseline/manual-full-001
```

结果为 `REPORT.md`（逐题面板）、`results.json`（全部候选/摘录/原文坐标/分组指标/指纹）和 `executor/`（当次工具源码）。退出码0只表示运行完整，不表示检索质量达标；1表示执行不完整；2表示输入或指纹不合法。重放不运行外部搜索、诊断报告或问诊流程。

## 冻结新版本

先确认后端容器名。只读导出可以在当前演示保护开启时进行：

```powershell
$ragSnapshot = Get-Content evals/rag-baseline/collect.py -Raw | docker exec -i -w /app medaxis-backend python -
if ($LASTEXITCODE -ne 0) { throw '只读导出失败，不继续构建' }
$ragSnapshot | Set-Content .ai/tasks/2026-10-07-rag-baseline/corpus-new.json -Encoding utf8
python evals/rag-baseline/build.py --corpus .ai/tasks/2026-10-07-rag-baseline/corpus-new.json --output .ai/tasks/2026-10-07-rag-baseline/frozen-new
```

`topics.json` 当前对应这4份文档，文档集合或原文改变后必须重新检查锚点/分组并生成新题库；不能直接把新版本分数当作旧版本收益。数据与模型出口可能含授权使用的指南文本，本机 `.ai` 原始材料不随公开克隆分发。后续若需要公开评测集，单独核对许可并构造可分发语料。

## 实际PostgreSQL基线的验收与复跑

本次用户明确授权后，一次45题真实查询向量批次已完成：text-embedding-3-small/1536维，1次HTTP请求、1,278 total_tokens。保护关闭约3.066秒后恢复true，额度limit=20/used=19未变。金额未取得；SDK无重试。已有向量可继续用于只读基线，不再关闭保护。

```powershell
python -m unittest discover -s evals/rag-baseline -p 'test_*.py' -v
python evals/rag-baseline/verify_stage2b.py --task .ai/tasks/2026-10-07-rag-baseline
```

应为13项测试OK，verified_stage2b，database_cases=45，replay_parity_cases=45，recorded_protection_restored=true，counter_unchanged=true。这里核对已留存的恢复记录；不是每次验证都重新查询当前数据库。当前恢复由本次独立只读查询确认，详见runtime-environment.json。

在当前Docker和源码仍匹配冻结版本时，复跑写新目录。此路径没有额外模型费用或数据库写入：

```powershell
python evals/rag-baseline/run_postgres.py --frozen .ai/tasks/2026-10-07-rag-baseline/frozen-v1 --embeddings .ai/tasks/2026-10-07-rag-baseline/query-embeddings.json --output .ai/tasks/2026-10-07-rag-baseline/postgres-manual-smoke-001 --ids R01,R06,R11,R20,R43
python evals/rag-baseline/run_postgres.py --frozen .ai/tasks/2026-10-07-rag-baseline/frozen-v1 --embeddings .ai/tasks/2026-10-07-rag-baseline/query-embeddings.json --output .ai/tasks/2026-10-07-rag-baseline/postgres-manual-full-001
```

容器入口使用stdin传程序，不写容器文件；数据库事务REPEATABLE READ/READ ONLY并rollback。每题记录粗召回、内部结果、最终摘录与阶段分数，运行前后查证实际语料/配置/源码等于冻结版本。更改源码/语料后必须为新实验明确建立版本，不能强行混用当前记录。外部重排供应商若启用，本入口拒绝伪装，需单独冻结其实际响应。

当前正常向量排序路径Hit@10=70%、严格字符覆盖Recall=67.5%、限定词覆盖70%。R19仅缺一个换行导致严格字符覆盖失败，不能当医学内容缺失。详情见[失败定位与路径比较](../../.ai/tasks/2026-10-07-rag-baseline/BASELINE_FINDINGS.md)。下一阶段先用独立反例校准空白评分，保留v1成绩，新量尺重新建立基线，不宣称算法收益。

## 生成新查询向量的前置条件

`collect.py --queries-base64` 接受1～60条合成查询，调用项目原EmbeddingService，记录供应商实际模型与usage。启用演示保护时明确拒绝后台调用；collect.py不会关闭保护、设置demo_actor或补充额度。temporary.py只用于用户明确批准的临时切换；本次授权已执行并恢复，后续新批次需遵守当时的保护及授权边界。

保存的真实向量可通过 `replay.py --embeddings <查询向量JSON>` 重放。模型、维度、有限数值必须匹配文档向量。SQLite重放应另有实际PostgreSQL入口验证；本次两条路径45题的粗候选、内部结果、最终来源及评分一致。不能用降级模式或随机向量填真实依赖缺口。

## 怎样评价优化

同一冻结语料、题库、量尺、模型和来源预算下保存前后记录；开发集用于调参，验收集按证据主题隔离。验收题不能反复用于选参数，已经查看的基线不再宣称盲测。专业核对修订gold必须新建数据版本，再重新建立基线。

Hit@K仅表示返回摘录与gold有字符重叠；Evidence Recall要求整个证据原文范围无缺口覆盖。限定词单列，防止命中治疗词却丢适用条件。MRR基于首个重叠，不是完整相关性分级；当前不报nDCG/Precision。无答案题候选返回率不等于报告错误成功率；临床准确率和报告错误成功率始终为null，直到各自入口及专业标注具备。

本阶段没有改变业务检索算法，不报优化收益。独立语义召回、上下文扩展、出处/版本/适用性元数据分别建立实验编号；收益必须来自可比逐题记录，并列出新增退步与未覆盖项。总分上涨也不能掩盖必要条件丢失。
