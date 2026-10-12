# 阶段7：原文支持测试集

**最新：问题覆盖判断与排序已接入、本地已验证，真实页面待验收。** [对比报告](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-09-evidence-support/query-assessment-v3/REPORT.md)保存真实模型结果（开发24/24、v4切片15/16）、失败记录、成本和边界。`query_experiment_verify.py`离线复核存档；`query_integration_replay.py`用历史原始JSON验证当前生产排序、引用和缓存，0模型调用，不能代替数据库或页面验收。生产源码已变化，旧`--check-production`报指纹漂移属预期，不得改冻结manifest。下文为历史资产与基线记录。

另有[query-development-v2开发集与基线](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-09-evidence-support/query-development-baseline-v2/REPORT.md)：24条、8新问题、16逐字片段，完整/partial_answer/另一用途各8条。旧gold范围重叠0、规范化字面查询复用0，未完成系统语义去重，共享语料且非盲测。v1候选编号带P可能提示部分回答，原件和试跑保留；正式开发采用不透明来源ID的v2。partial_answer不是无关资料，不应自动删除。开发集采用显式--folder/--assets-dir参数，v4保留回归用途；默认v3兼容行为不变。

**当前有效修订版：v4，53题。** 47题原样继承、5题按审核修订、1题新增完整条件正例；对应基线53记录/36执行/17缺能力。当前入口为[新版报告与验收](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-09-evidence-support/baseline-v4-authorized/REPORT.md)。本目录默认参数仍指向v3以保留历史兼容：v4资产校验/评分使用`--folder frozen-v4目录`，实际执行/基线复核使用`--assets-dir frozen-v4目录`，同时指定新的运行输出目录。下文为v3原协议及历史结果，不应把52题结果作为v4完整运行结果。v4不是独立开发集，专业审核仍待办。

当前交付是**52题冻结资产及校验/评分工具**；2026-10-09已运行[生产函数诊断基线](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-09-evidence-support/baseline-v2/REPORT.md)：36题有实际入口，16题适用性能力缺失，不存在完整52题语义准确率。52题来自8个原文主题、24组正反对照，并非52个独立临床病例；医学标签为AI草稿，专业审核0题，同语料非盲测。

入口：[阶段报告与验收](D:/CAI-Projects/medaxis/docs/product/EVIDENCE_SUPPORT_EVALUATION.md)。当前有效版本为 [frozen-v3](D:/CAI-Projects/medaxis/.ai/tasks/2026-10-09-evidence-support/frozen-v3/QUESTIONS.md)。frozen-v1限定词有一处转述，校验失败；v2执行编号带正反提示，主代理交付自审发现并修正。两版保留，不用于基线。

## 如何检查

在MedAxis项目根运行，均离线、不调用模型、不写业务数据库：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/verify.py --check-production
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/test_assets.py
```

预期分别显示 `PASS_ASSET_VALIDATION_ONLY`、52题/8原文/24对照组、新旧gold重叠0，以及16项测试OK。`--check-production`另外核对冻结时4个源码指纹；后续优化导致它失败是版本变化提示，应记录新运行版本，不能偷偷更新旧manifest。

`verify.py`逐字校验原文、字符坐标、SHA、限定词、输入内容、旧45与旧20题重用/原文重叠；它不判断临床正确，也不证明检索新题时找得到这些资料。

## 题目与执行协议

| 检查 | 数量 | 标签与含义 |
|---|---:|---|
| 问题具体要求 | 16 | answers / does_not_answer：此候选片段能否回答问题；负例来自同份指南的另一主题 |
| 报告陈述支持 | 16 | supported / contradicted；执行时也允许insufficient，但此版本没有该类金标 |
| 合成条件适用性 | 16 | applicable / not_applicable / unknown：只核对指定用途所需条件，不批准诊疗安排 |
| 指定版次 | 4 | version_mismatch：现有摘录不能支持2028版更新；本版只有版本负例 |

执行器应只读 `inputs.json`，独立给出预测；预期标签位于 `dataset.json`。执行ID为不含正反提示的内容指纹，输入按指纹排序，避免正例总在前面；展示编号仅供审核者查看。相邻chunk可能共享，题目由主代理可见，因此仍不能称盲测。数据只含合成条件与已冻结公开规范，不含真实患者信息。

**这里是给定候选资料的判别集，尚不是端到端检索召回集。** 适切性、适用性、句子支持需分别执行，不能把三个标签混成一个相似度；疾病名称相同不能代替内容要求，来源官方不能代替支持关系。

输出预测JSON格式：

```json
{
  "version": "evidence-support-v3",
  "run_metadata": {
    "kind": "actual_candidate_assessment",
    "method": "填写实际执行方法",
    "started_at": "填写实际执行时间",
    "source_sha256": "填写实际代码指纹与模型/配置版本"
  },
  "predictions": [
    {"id": "从inputs.json复制对应执行ID", "label": "answers", "reason": "填写实际判断依据"}
  ]
}
```

示例只解释格式；正式输出必须有全部52个ID。不得复制预期标签充当生产预测。

评分：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/score.py --predictions <实际预测文件> --output <新结果文件>
```

缺题、重复ID、额外ID、非法标签、版本不符直接失败。结果给出各类正确率、错误接受率、混淆矩阵、每个错题及24组对照是否同时判断正确；unknown当成适用会计错误接受。结果不覆盖旧文件。

## 下一次怎样得到优化证据

1. 不改生产算法，先对52个固定输入运行实际方法，保存原始预测、模型/配置/源码指纹及时间。先运行少量smoke，核对执行协议；完整52题必须全部保留。
2. 专业审核人员在**另存的**review.csv中核对原文、标签与条件，给出审核身份/意见。冻结模板不直接编辑。需改gold时建新版本，旧结果重新按新版本计算并保留。
3. 优化后用完全相同输入、同配置和评分工具重新执行。逐题列改善、退步及不变；比较错误接受率及正反对照同时正确数，不能只报告整体平均。
4. 本集不能用于不断试阈值选最优结果。需要调参时另建开发集；独立验收还需要专业审核的新语料/新主题。

当前没有声称优化有效。测试中的人为预测只用于检查评分器，不能进入生产基线成绩。

## 当前基线怎样验收

无需Docker或模型调用，复核存档：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/baseline_verify.py
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/test_baseline_verify.py
```

预期52条记录、36执行、16能力缺失、执行异常0；正确候选8/8保留，不回答问题的候选6/8仍保留，16条陈述全部needs_review，4个显式版次反例过滤。测试9项OK。候选保留与逐字确认是投影指标，不是生产模型给出的语义标签。

当前环境未配置reranking；生产函数自然降级，未替换供应商或分数。只读事务核对实际数据库8个原文片段/标题/URL与冻结输入一致，观测HTTP0、额度和保护不变。未运行向量召回、外部搜索、全报告或常驻HTTP路径。

冻结manifest中的baseline_status=NOT_RUN（校验输出production_baseline_at_freeze）是冻结时事实；当前状态由阶段入口及实际运行记录维护，不能修改冻结manifest。

如果需要重跑实际容器，用**新的**输出目录，先smoke再full；输出目录限制在本阶段活动目录且不覆盖旧结果：

```powershell
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/baseline_runner.py smoke --output-root .ai/tasks/2026-10-09-evidence-support/replay-next
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/baseline_runner.py full --output-root .ai/tasks/2026-10-09-evidence-support/replay-next
backend/.venv/Scripts/python.exe -X utf8 evals/evidence-support/baseline_verify.py --folder .ai/tasks/2026-10-09-evidence-support/replay-next --check-production
```

这是同一源码版本的复现命令。本轮不为填满52题而新写语义判断器；缺能力不能用unknown算对，也不生成冒充完整运行的predictions.json。后续源码/供应商或实验协议变化时另建运行版本、明确比较边界，不能修改当前基线。
