# 问诊与引用对比评测

固定响应控制层重放与真实模型探测分开统计。产品验收见[验收文档](../../docs/product/CONSULTATION_OPTIMIZATION_ACCEPTANCE.md)，最新结果见[回归修复报告](../../docs/product/CONSULTATION_REGRESSION_FIX.md)，原三例探测见[历史对比报告](../../docs/product/CONSULTATION_OPTIMIZATION_COMPARISON.md)。所有案例是合成数据。

## 固定重放

`catalog.json` 当前有 17 项预期，由 `score.py` 逐项校验。2026-10-03 修正 `soft_budget`：必要项未询问必须继续问；新增必要缺口恢复生成及失败阻止总结两项。`probe.py` 加载指定目录的实际应用代码并检查 import 路径。两组子进程相互隔离，模型和检索响应固定，持久化使用替身；数据库连接事件拦截器禁止真实连接。`run_compare.py` 使用无效测试 DB 地址用于配置导入，不加载患者数据。

从项目根目录执行；`--baseline/--current` 指向各自包含 `app/` 的后端目录。输出目录必须是新的，脚本拒绝覆盖证据。

```powershell
$env:PYTHONIOENCODING='utf-8'
backend\.venv\Scripts\python.exe evals/consultation-optimization/run_compare.py --baseline .ai/tasks/2026-10-03-consultation-regressions/baseline/backend --current backend --output .ai/tasks/2026-10-03-consultation-regressions/comparison-recheck-1
```

预期当前代码 17/17 且 exit 0；本次修复前快照为 14/17。原 2026-10-02 的 3/15 → 15/15 是旧目录和错误预算标准下的历史结果，不与本次混算。输出包括两组原始记录、日志、逐项失败约束与目录哈希。快照位于本地忽略目录，不随 Git 分发；新环境需提供待比较的真实源码基线，不能将当前代码复制成 baseline 冒充旧版。

评测观察实际发出的卡片、待答状态、失败、停止原因、缺口与模型可用的来源上下文。报告实际引用的列表单独保留。来源相关性的三个用例使用固定候选和重排替身，因此只验证选择机制；没有执行生产检索，也没有测召回率。`holdout` 是历史 ID，不表示盲测。

## 历史三例真实模型探测及复跑

本节脚本针对 2026-10-02 的三例。2026-10-03 的腹泻必要缺口、互补病史、未知回答后的续问状态及真实引用绑定使用独立合成输入，原始脚本和记录位于 `.ai/tasks/2026-10-03-consultation-regressions/`；见修复报告。两组数据不混算。

`live-fixtures.json` 定义预期的三例。`prepare_live.py` 仅打包指定后端 Python 源码和合成输入，生成 stdin 脚本，不打包 `.env` 或凭证。脚本在容器临时目录加载源码，通过既有 `LLMService(platform="web")` 查询模型配置。事务 `SET TRANSACTION READ ONLY`、结束 rollback；不读患者、不执行检索或保存会话。每例最多 3 次模型调用、每次 35 秒无重试、每例工作流最多 115 秒。

以下是本轮同类探测的可复制步骤；需要已配置的测试后端容器 `medaxis-backend` 和模型。会产生模型调用费用；只在已授权的测试环境运行。`$probeTask` 是任务输出位置，前后两组均需运行。

```powershell
$probeTask='.ai/tasks/2026-10-02-consultation-optimization'
backend\.venv\Scripts\python.exe evals/consultation-optimization/prepare_live.py --source-root "$probeTask/baseline/backend" --label before --output "$probeTask/live-before-recheck-bootstrap.py"
Get-Content -Raw "$probeTask/live-before-recheck-bootstrap.py" | docker exec -i medaxis-backend python - | Set-Content -Encoding utf8 "$probeTask/live-before-recheck.json"
backend\.venv\Scripts\python.exe evals/consultation-optimization/prepare_live.py --source-root backend --label after --output "$probeTask/live-after-recheck-bootstrap.py"
Get-Content -Raw "$probeTask/live-after-recheck-bootstrap.py" | docker exec -i medaxis-backend python - | Set-Content -Encoding utf8 "$probeTask/live-after-recheck.json"
backend\.venv\Scripts\python.exe evals/consultation-optimization/summarize_live.py --before "$probeTask/live-before-recheck.json" --after "$probeTask/live-after-recheck.json" --output "$probeTask/live-summary-recheck.json"
```

PowerShell 7 的 `utf8` 无 BOM；Windows PowerShell 5 的 `utf8` 带 BOM，汇总读取器用 `utf-8-sig` 兼容这类输出。项目源码和文档使用 UTF-8 无 BOM。不要输出容器环境或模型配置内容。Docker daemon 权限可能需要环境授权；没有权限时保留脚本并记录未执行，不能用固定重放代替真实模型证据。

本轮最终统计实际使用 `live-before.json` 与 `live-reviewed.json`；重跑结果应独立保存，不覆盖这两份及早期失败记录。

```powershell
backend\.venv\Scripts\python.exe evals/consultation-optimization/summarize_live.py --before .ai/tasks/2026-10-02-consultation-optimization/live-before.json --after .ai/tasks/2026-10-02-consultation-optimization/live-reviewed.json --output .ai/tasks/2026-10-02-consultation-optimization/live-summary-recheck-existing.json
```

评分器要求全部预期 ID、无重复/错误、调用 usage 完整；空/缺失/失败数据集 exit 1，缺少 usage 时成本字段不可用。发题数为本次决策返回的卡片数；“已记录维度重问”按规范化信息键与 fixture 的 recorded_keys 比较。总 Token 是三例所有调用 usage 的和；总耗时是三个工作流 elapsed_ms 的和，不是报告生成耗时。需同时读 action/sufficient 和缺口原始响应，避免把阶段总结零题解释为医学充分。

每组仅一次，不代表统计显著性、完整问诊质量或全流程成本。原始响应只含合成资料，可以核查兼容失败、截断和调用数；不得静默丢失失败场景或只选最优的一组汇报。
