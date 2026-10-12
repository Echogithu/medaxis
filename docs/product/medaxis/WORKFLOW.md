# MedAxis 生命周期入口

> Status: REVIEW · 模式：Standard · 当前 Phase：0 / active · 更新：2026-10-09

本表管理全项目产品评审的后续关口，不表示既有项目从未开发，也不把本次图文文档制作当作应用重设计。机器读状态见 [phase-manifest.yaml](phase-manifest.yaml)。

| Phase | applicability | status | 真源 / 重新进入条件 |
|---|---|---|---|
| 0 产品定义 | required | active | [PRD](PRD.md)、[Readiness](DEVELOPMENT_READINESS.md)；待Owner评审与关键门解除 |
| 1 IA/UX | merged → 0 | pending | [USER_FLOWS](USER_FLOWS.md)；现有导航盘点合并评审，改变入口时单独重开 |
| 2 Wireframe | deferred | pending | 本次无应用页面结构修改；获准重构旧医生/报告页面时重开 |
| 3 视觉设计 | deferred | pending | 文档阅读版不替代应用视觉设计；批准应用视觉变更时重开 |
| 4 技术设计 | deferred | pending | [领域模型](DOMAIN_MODEL.md)及[架构](../../engineering/architecture.md)；产品批准并明确权限/schema变化时重开 |
| 5 实施 | deferred | pending | 本次不改应用；技术契约及实施授权明确后重开 |
| 6 联调 | deferred | pending | 现有专项验收入口；合成隔离/目标环境验证授权明确后重开 |
| 7 发布 | not_applicable | pending | 本次只交付文档；指定目标环境、发布授权、回滚与负责人后重评 |

## 权威文档指针

- 产品真源：[PRD](PRD.md)与[专项规格索引](README.md#文档真源与冲突处理)。
- code_index：`null`，未定位独立代码索引；本次 [EVIDENCE](EVIDENCE.md) 是产品覆盖证据，不冒充工程 code_index。
- 技术白皮书：未定位独立文档；现有 [architecture](../../engineering/architecture.md) 登记为工程架构参考。
- conventions：[AGENTS.md](../../../AGENTS.md)。
- trace/handoff：`null`；本次活动记录在 `.ai/tasks/2026-10-09-product-dossier/`，未创建另一套正式跨任务 trace。

**唯一下一动作：** 评审 [DECISIONS](DECISIONS.md) 的范围、权限与数据政策，同步 living docs 并重新计算门禁；不自动开始应用开发或发布。
