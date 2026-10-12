# 评估记录与优化证据

2026-10-07。入口：[项目评估规范](../../docs/product/EVALUATION_PROTOCOL.md)。仅使用 Python 标准库记录与比较，执行现有应用探针需要后端虚拟环境；不增加依赖、不修改产品行为或数据库。

## 第一批可执行数据

复用 [consultation-optimization/catalog.json](../consultation-optimization/catalog.json) 的 17 条固定案例：14 条问诊控制、3 条来源筛选。题集只有一份真源，每次运行复制冻结版本，不另维护题目副本。模型、搜索、持久化是替身，应用控制逻辑来自当前源码快照，探针禁止数据库连接。

这些题目验证已有信息复用、未知与矛盾保护、必要缺口补问、失败语义，以及内外来源排序，**不验证实际语义召回、临床充分性或诊断准确率**。10 条患者侧合成流程另见 [patient-smoke](../patient-smoke/README.md)，不把其 `DEFINED_NOT_RUN` 状态计为通过。

## 可复跑命令

从项目根目录执行。每次换一个输出目录；已存在目录会拒绝覆盖。

```powershell
python -m unittest discover -s evals/evidence -p test_run.py -v

# 修改前，冻结当前源码与17条输入
backend/.venv/Scripts/python.exe evals/evidence/run.py run --label before --output .ai/evaluations/EXP-001/before

# 完成一次明确的优化后执行
backend/.venv/Scripts/python.exe evals/evidence/run.py run --label after --output .ai/evaluations/EXP-001/after

# 写入本次假设与具体改动，生成逐题对比
backend/.venv/Scripts/python.exe evals/evidence/run.py compare --before .ai/evaluations/EXP-001/before/record.json --after .ai/evaluations/EXP-001/after/record.json --hypothesis "明确本次要改善的行为" --change "实际修改了什么，以及唯一主要变量" --output .ai/evaluations/EXP-001/comparison
```

小样本可用 `--ids known_reuse,pending_guard,generation_failure,trusted_irrelevant,shared_reranking`。不同子集不允许比较。先检查原始输出与评分能区分正确、错误、缺失，再扩量。

## 运行产物

| 文件 | 用途 |
|---|---|
| `dataset.json` | 冻结输入与期望；SHA-256 进入成绩单 |
| `raw.json` | 每题实际输出，不只保存汇总分数 |
| `source/app/` | 当次应用 Python 源码快照，包含未提交源码内容；不复制 `.env` 或数据 |
| `probe.py / score.py / runner.py` | 冻结执行器与评分器 |
| `dependencies.json` | 当次 Python 依赖名称和版本，指纹用于阻止跨环境混比 |
| `execution.json / execution.log` | 实际命令、退出码和输出；失败也保留 |
| `record.json` | 模式、环境、源码/数据/工具指纹、逐题成绩；缺失用量为 null |
| `comparison/REPORT.md` | 假设、改动、逐题前后分数、改善与退步、证据路径 |

运行 exit 0 表示全部固定约束通过；exit 1 表示完整运行但存在约束失败；exit 2 表示执行或证据不完整，不能作成功基线。比较 exit 0 表示可比较且无新增退步，**不表示有效提升**；必须读取 `verdict`。出现退步 exit 1；题集、评分器、执行器、模式或环境变化 exit 2。

结论只允许：`improved_on_this_control_set`、`no_quality_gain`、`regression`；不可比较时显式报错。即使净分相同，只要某题由通过变失败，仍标为退步。耗时与成本不在此固定响应工具中估算。

## 本次实测

2026-10-07 当前源码 17/17，同版本独立复跑 17/17，逐题无变化；判定 `no_quality_gain`。这是记录与对比链路的校准，**不是某项 RAG 优化的收益**。原始本地证据位于 `.ai/tasks/2026-10-07-evaluation-evidence/`，不随 Git 分发；后续用户可用以上命令独立复跑。

此工具目前只运行固定控制层题集。真实 RAG 需冻结文档与索引、标注原文位置、执行实际检索并保存阶段结果；临床正确性需专业评审，不能用本工具的通过率替代。
