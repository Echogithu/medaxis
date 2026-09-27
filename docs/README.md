# MedAxis 文档索引

本索引按用途组织项目文档。文件位置保持不变，便于现有相对链接继续工作。

## 从这里开始

1. 阅读[项目 README](../README.md)，了解项目边界和本地启动方式。
2. 阅读[系统架构](./engineering/architecture.md)，了解入口、模块和主要数据流。
3. 按改动范围查看[后端](./engineering/backend.md)、[前端](./engineering/frontend.md)、[数据库](./engineering/database.md)或[部署配置](./engineering/deployment.md)。
4. 产品范围和现状审查见[患者侧聚焦 PRD](./product/PORTFOLIO_PRD.md)、[审查型 PRD](./product/PRD.md)及[患者侧闭环独立审查](./product/PATIENT_DEMO_CLOSURE_REVIEW.md)。

## 工程参考

| 文档 | 用途 |
|---|---|
| [architecture.md](./engineering/architecture.md) | 系统组成、问诊和诊后对话主流程 |
| [backend.md](./engineering/backend.md) | API 入口、服务模块、权限与实现边界 |
| [frontend.md](./engineering/frontend.md) | 页面路由、身份状态、API 客户端与测试入口 |
| [database.md](./engineering/database.md) | 数据模型、会话层级、RAG 存储与迁移位置 |
| [deployment.md](./engineering/deployment.md) | 本地 Compose、端口、数据卷与生产配置边界 |

这些文档是源码和配置的静态参考，不代表服务当前运行或生产环境已验收。

## 产品范围、评审与验收

| 文档 | 用途与状态 |
|---|---|
| [PORTFOLIO_PRD.md](./product/PORTFOLIO_PRD.md) | 患者侧作品范围、MVP、指标与证据边界；状态为 REVIEW |
| [PATIENT_DEMO_CLOSURE_PLAN.md](./product/PATIENT_DEMO_CLOSURE_PLAN.md) | 合成数据演示闭环的范围、结果与未验证项 |
| [PATIENT_DEMO_CLOSURE_REVIEW.md](./product/PATIENT_DEMO_CLOSURE_REVIEW.md) | 患者侧独立审查、验证范围和剩余风险 |
| [PRD.md](./product/PRD.md) | 完整需求与实现差距的历史审查；旧问题须回查当前源码 |
| [todos.md](./product/todos.md) | 高优先级问题摘要，不代表已批准排期 |
| [patient-smoke](../evals/patient-smoke/README.md) | 10 个合成冒烟案例；状态为 `DEFINED_NOT_RUN` |

本地 `.ai/tasks/` 中的计划、截图、脚本和原始运行记录属于过程资料，不随项目文档分发。稳定结论以本节的计划和审查文档为准。

## 作品集材料

- [RESUME_GUIDE.md](./portfolio/RESUME_GUIDE.md)：AI 工程师/产品经理的技术证据、优化顺序与简历表达。

## 历史提案与执行交接

| 文档 | 阅读边界 |
|---|---|
| [PROPOSAL.md](./archive/PROPOSAL.md) | 2026-08-16 的历史架构提案；其中成熟度和“已实现”表述不是当前基线 |
| [LUNA_EXECUTION_HANDOFF.md](./archive/LUNA_EXECUTION_HANDOFF.md) | 历史执行交接，引用本地任务记录；不作为新的实施指令 |

## 医学参考 PDF

这些文件是项目内的参考资料；使用时应核对原始发布机构、版本和适用范围。

### 诊疗指南与方案

- [儿童肺炎支原体肺炎诊疗指南（2025年版）](<./medical/guidelines/儿童肺炎支原体肺炎诊疗指南（2025年版）.pdf>)
- [儿童急性感染性腹泻病诊疗规范（2020年版）](<./medical/guidelines/儿童急性感染性腹泻病诊疗规范（2020年版）.pdf>)
- [流行性感冒诊疗方案（2025年版）](<./medical/guidelines/流行性感冒诊疗方案（2025年版）.pdf>)
- [Fever in under 5s: assessment and initial management](<./medical/guidelines/fever-in-under-5s-assessment-and-initial-management-pdf-66141778137541.pdf>)

### 药品参考与说明书

- [布洛芬混悬滴剂（美林，2021-11-09 版）](<./medical/medications/儿童药物参考-布洛芬混悬滴剂（美林，2021-11-09版）.pdf>)
- [布洛芬混悬液（美林，2021-05-06 版）](<./medical/medications/儿童药物参考-布洛芬混悬液（美林，2021-05-06版）.pdf>)
- [对乙酰氨基酚片说明书](<./medical/medications/儿童药物参考-对乙酰氨基酚片（说明书）.pdf>)
- [口服补液盐散 III 说明书](<./medical/medications/儿童药物参考-口服补液盐散III（说明书）.pdf>)
- [磷酸奥司他韦胶囊（达菲，2025-02-20 版）](<./medical/medications/儿童药物参考-磷酸奥司他韦胶囊（达菲，2025-02-20版）.pdf>)

## 阅读边界

- `PRD.md` 和 `PORTFOLIO_PRD.md` 是评审材料，不替代当前源码事实或开发授权。
- 患者侧演示结论仅覆盖合成数据与明确列出的测试范围，不证明真实模型质量、临床有效性或医生闭环。
- 历史验收数字只代表各自记录的范围，不应相加为统一覆盖率，也不代表本轮重新运行。
