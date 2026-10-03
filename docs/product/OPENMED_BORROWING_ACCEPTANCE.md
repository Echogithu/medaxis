# OpenMed 借鉴功能与验收

2026-10-01，本地业务集成。三项能力进入 MedAxis 既有就医准备、报告和出站请求流程；没有新增生产依赖、数据库迁移或部署。本次借鉴设计思路，中文实现由本项目编写，不复制上游代码。

## 借鉴了什么

| 功能 | 用户能观察到的变化 | 参考来源 |
|---|---|---|
| 原话语境提示 | “母亲患有糖尿病；我目前咳嗽3天；既往肺炎已痊愈”分别提示家属信息、当前表述、既往表述；未知和前后冲突继续待核对 | [OpenMed 多轴断言状态](https://github.com/maziyarpanahi/openmed/blob/master/openmed/clinical/grounding/assertion_grounding.py) |
| 逐条原文核对 | 引用卡展示每条报告陈述的“原文一致”或“待核对”，并展示对应原文；有引用编号不等于陈述获支持 | [OpenMed clinical brief 的证据门禁](https://github.com/maziyarpanahi/openmed/blob/master/openmed/clinical/brief.py) |
| 外发文本遮蔽 | 发送给模型、embedding 和外部搜索的文本遮蔽有限标识，原始病情与病程数值保留 | [OpenMed 去标识能力](https://github.com/maziyarpanahi/openmed#readme) |

此前实际 SDK 实验的中文默认链路仍维持 HOLD，详见 [SDK_RESULTS.md](../../evals/openmed-transfer/SDK_RESULTS.md)。这里采用有限规则及精确摘录核对，不宣称达到 SDK 的 NER、NLI 或完整医疗去标识能力。

## 怎么验收

使用测试账户和合成文本，不输入真实患者资料。重启本地后端并启动前端后执行以下步骤；若运行服务仍使用旧代码，页面不会自动获得本次功能。

1. **病情核对与复制**：在问诊的伴随情况中输入“母亲患有糖尿病；我目前咳嗽3天；既往肺炎已痊愈”。完成问诊后，进入“问诊记录 → 准备去就诊 → 核对或修改病情”。应能看到三段原话和对应语境提示；复制摘要后标签应一致。追加“不清楚是否过敏”仍显示未知；前后给出“测到38.5℃”和“我没有发热”，两条原话应同时留在待核对中。更正原话后保存再复制，不得沿用未保存前的语境。
2. **引用核对**：打开新生成报告，点击 `[S1]`，展开“查看原文片段”。每条已引用的陈述均有状态。若来源为“目前没有发热。”，报告完整照录这一句可以显示“原文一致”；“发热”必须待核对。正确意译也可能待核对。真实模型未必生成照录句，不能要求每份报告一定出现“原文一致”。确定性正反例由自动化测试提供。旧报告缺少逐条记录时，应显示“尚无逐条核对记录”。
3. **文本遮蔽**：通过下方真实 SDK 请求捕捉测试验收。合成输入“姓名：陈小禾，电话：13800000000；咳嗽3天，体温39℃”在出站 HTTP 请求体中不能出现姓名和电话，仍有 `3天`、`39℃`；本地原话保持完整。浏览器 Network 看到的是发往本地后端的原文，不能用它判定后端发往 provider 的脱敏效果。

详细手动清单见 [manual-test-openmed-integration.md](../../.claude/manual-test-openmed-integration.md)。

## 可复跑验证

后端选定测试不使用数据库或真实 provider。以下 PowerShell 在项目 `backend` 目录运行，关闭 dotenv，仅给此 Python 进程设置合成测试配置：

```powershell
$testCode = @'
import os
os.environ["SECRET_KEY"] = "synthetic-test-secret-not-for-runtime"
os.environ["API_KEY_MASTER_KEY"] = "synthetic-test-master-not-for-runtime"
from app.core.config import Settings
Settings.model_config["env_file"] = None
import pytest
raise SystemExit(pytest.main([
    "tests/test_clinical_context.py", "tests/test_text_privacy.py",
    "tests/test_claim_evidence.py", "tests/test_knowledge_citations.py",
    "tests/test_case_preparation_semantics.py", "tests/test_patient_llm_errors.py",
    "tests/test_preparation_departments.py", "-q", "--tb=short", "-p", "no:cacheprovider"
]))
'@
$testCode | .venv/Scripts/python.exe -
```

前端在 `frontend` 目录运行：

```powershell
npm test
node_modules/.bin/tsc.cmd -p tsconfig.app.json --noEmit
node_modules/.bin/eslint.cmd src/state/casePreparation.ts src/state/reportCitations.ts src/components/ReportCitationCard.tsx src/components/PatientReportBody.tsx src/patient/components/CasePreparationPanel.tsx
npm run build
```

本轮记录：后端 88 个测试、前端 49 个测试、TypeScript、上述定向 ESLint、Python 语法编译均 exit 0；构建 exit 0，仍有大 chunk 和插件耗时提示。Python Ruff 不在现有环境，未安装、未宣称其通过。独立只读审查未发现阻塞缺陷；审查指出的旧包 API 失效和真实工具 schema 捕捉缺口已补测。

浏览器使用真实 Python `build_package` 和 `attach_knowledge_citations` 生成的合成 API 数据，在 1440×1000 与 390×844 下核对引用、原话、复制及页面错误；两种尺寸通过，等待展开动画后检查内容尺寸与截图。它没有连接真实数据库或模型。原始命令、截图、请求捕捉和运行记录保存在本地 `.ai/tasks/2026-09-30-openmed-transfer/`；不把它表述为生产端到端通过。

## 集成位置与兼容性

- `backend/app/services/clinical_context.py` → `case_preparation.build_package` → `CasePreparationPanel` / `preparationSummary`。语境保留 Unicode 字符位置及来源 ID；标签仅为规则提示，不改已有断言或科室逻辑。策略版本参与准备包 fingerprint，旧包需重新生成后复制。
- `knowledge_citations.check_claim_evidence` → `DiagnosisAgent.run_full_diagnosis_workflow` → 保存的结构化报告 → `PatientReportBody` / `ReportCitationCard` 与流式 Markdown。生成端不能自报成功，状态和位置由服务端重算；直接 `analyze` 清除生成端自报来源和成功状态。未建立引用的陈述不产生核对记录。
- `text_privacy` → `LLMService` 普通、流式、工具、结构化及回退、vision 文字请求；`EmbeddingService.embed` 与 `ExternalSearchAgent`。调用编号保留；工具内容和 JSON 参数按值遮蔽；遮蔽副本不会写回本地原话。搜索查询日志只记录长度。
- 新字段为可选加性字段，已有报告仍可阅读，不自动补造历史核对记录。没有修改数据库 schema。

## 边界与风险

1. 中文语境规则覆盖有限词项，复杂主体、跨句时间或双重否定可能误判；混合主体或时间提示尽量待核对。它不进行医学实体识别、风险诊断，也不提高既有科室推荐的临床可信度。
2. “原文一致”只证明整条陈述与检索摘录的一段完整句精确一致；不是 NLI，不证明资料正确、适用于该患者或诊断正确。意译、混合推理、重复位置和缺证据保持待核对。坐标相对检索返回的摘录，不是完整 PDF 页坐标。
3. 规则遮蔽姓名、电话、邮箱、身份证、明确病历号/地址等有限格式；合成题集已公开，不是盲测，不能保证真实文本全部去标识。原始图片像素、上传文件、URL 隐含信息和协议身份字段不在遮蔽保证内。UUID 等关联信息仍可能构成可链接信息。
4. 已验证的是本地工程调用链与合成数据，未重新运行真实模型或数据库主线，没有部署，也没有专业临床审核。embedding 文本遮蔽可能影响含姓名/编号的检索，真实检索质量需另评估。

## 恢复

任务开始前保留了所涉及既有业务文件的快照，位置为本地任务目录 `integration-baseline/`。它只覆盖本任务编辑前的局部状态，不是整仓库备份。恢复须先逐文件比较本轮差量并获得用户决定，保留已有及后续改动；不要用整仓 reset 或批量覆盖。无数据库迁移需要回退。
