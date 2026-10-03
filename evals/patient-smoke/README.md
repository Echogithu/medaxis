# 患者侧合成冒烟评测集

Status: **DEFINED_NOT_RUN**｜2026-09-27

2026-09-29 已新增 [T06 DeepSeek 部分成绩单](results/2026-09-29-t06-deepseek-live.json)：SM-01–04 真实模型、25 项映射工程断言与合成内部引用分别记账。目录文件仍保持 `DEFINED_NOT_RUN`，表示固定题集本身不冒充完整 10 案例验收；实际私有知识库文档外发和隔离报告中的外部 URL 仍未验证。

这是作品集约定的第一批 **10 个固定合成案例**，不是已经跑完的分数。用途：把输入、禁止推断、失败语义和现有回归测试钉死，之后用同一口径跑替身演示和真实模型。

权威文件：

- 题集：[`catalog.json`](catalog.json)
- 空成绩单：[`results.template.json`](results.template.json)
- 校验/映射：[`run_eval.py`](run_eval.py)

产品入口：[聚焦 PRD](../../docs/product/PORTFOLIO_PRD.md) 第 7 节、[作品集指南](../../docs/portfolio/RESUME_GUIDE.md)「先固定评测集」。

## 案例一览

| ID | 场景 | 主要验证 | 当前可自动映射 |
|---|---|---|---|
| SM-01 | 信息完整 | 问诊→报告→同病例准备/反馈 | 病例幂等保存；演示脚本（替身） |
| SM-02 | 缺少过敏史 | 未知 ≠ 无过敏 | 准备包缺键 → `unknown.allergies` |
| SM-03 | 缺少起病时间 | 不得编造发病日期 | 无；需真实模型 + 人工对照 |
| SM-04 | 前后矛盾 | 不得静默选一边 | 无；需真实模型 + 人工对照 |
| SM-05 | 上传无法解析 | 失败可见，不当正常化验 | 解析 worker 成功/失败落库 |
| SM-06 | 模型超时 | 不得直接出诊断 | 首轮失败/超时回归 |
| SM-07 | 报告成功、保存失败 | 不显示已保存 | 病例回滚；准备保存失败保旧版 |
| SM-08 | 提交旧版本 | 409，不覆盖新内容 | 准备 CAS；诊后反馈 revision |
| SM-09 | 患者 A 访患者 B | 拒绝且不泄漏 | 病例/准备/反馈/材料归属 |
| SM-10 | 清缓存重登 | 只恢复已保存记录 | 缓存丢失后读回报告；演示脚本 |

SM-02 / SM-03 / SM-04 未做专业医学标注，只能评「有没有补造事实」，不能评「诊断对不对」。

## 怎么跑

校验题集（不连数据库、不调模型）：

```powershell
python evals/patient-smoke/run_eval.py --check --write-template
```

跑已映射的工程 pytest（需要 PostgreSQL 测试库，**不要**指向演示库；`conftest.py` 会话结束会 `drop_all`）：

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://.../medaxis_eval_suite_isolated'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
python evals/patient-smoke/run_eval.py --pytest
```

真实模型按案例脚本或隔离 runner 执行。把带日期的成绩写到 `evals/patient-smoke/results/`，保留未执行项及成本缺失值，不把目录校验或替身测试计作模型结果。

## 记账规则

| 观察到 | 允许写 |
|---|---|
| `--check` 通过 | 题集定义合法 |
| 映射 pytest 通过 | 对应工程契约在该测试库成立 |
| 替身 E2E 通过 | 认证/API/持久化闭环，生成逻辑为替身 |
| 真实模型按脚本跑完并留日志 | 该模型版本的冒烟结果 |
| 人工核对未知/矛盾/引用 | 来源忠实性，不是临床准确率 |

禁止：把 10 个案例写成「已验收」；把替身结果写成模型质量；把 SM-01 成功外推到 SM-03/SM-04。
