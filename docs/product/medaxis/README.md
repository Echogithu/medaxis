# MedAxis 产品文档集

> Status: REVIEW · v1.0 · 2026-10-09 · 主要读者：产品评审与研发协作

**医枢 MedAxis：让患者把分散的症状、检查资料和诊后记录，整理为有来源、可核对、可再次找到的就医资料。** 医生通过患者授权的定向咨询提供健康建议；管理端维护账号、资料与模型服务。

## 三分钟读懂

![MedAxis 产品全景](visuals/product-map.png)

| 想了解什么 | 从哪里看 |
|---|---|
| 产品为什么存在、服务谁、做什么 | [全项目 PRD](PRD.md) |
| 一个用户动作怎样算成功 | [行为与验收规格](PRODUCT_SPEC.md) |
| 病例、报告、咨询之间是什么关系 | [领域模型](DOMAIN_MODEL.md) |
| 正常、失败、取消和恢复怎么走 | [用户流程](USER_FLOWS.md) |
| 页面、接口与历史证据对应到哪里 | [项目事实与覆盖矩阵](EVIDENCE.md) |
| 下一步能否进入开发规划 | [就绪评估与实现差距](DEVELOPMENT_READINESS.md) |
| 哪些已决定，哪些需要讨论 | [决策与开放项](DECISIONS.md) |
| 各阶段如何衔接 | [生命周期入口](WORKFLOW.md) |

可视化阅读：[文档阅读版](index.html) · [交互思维导图](visuals/product-mindmap.html) · [导图静态图片](visuals/product-mindmap.png) · [图源及生成说明](visuals/README.md)。Markdown 是内容真源，HTML 和图片是派生阅读材料。

## 阅读边界

- **当前代码：** 本次只读核对工作区路由、服务及状态；未启动应用、未连接业务库、未调用模型。
- **历史证据：** 保留其日期、样本和运行条件，不等于本次重新验证，也不证明临床有效性。
- **规划需求：** 未完成能力与建议优先级明确标注；整份产品包尚未获批。
- **演示素材：** 阅读版的患者页面截图来自现有[合成预置重放](../../media/README.md)，不证明真实检索、业务保存或权限验收。

四种标记：`FACT` 有出处的事实；`OWNER_DECISION` 有来源的用户裁决；`ASSUMPTION` 可修改的建议；`UNKNOWN` 缺少证据的事项。代码里名为 diagnosis 的字段不自动赋予内容医疗效力。

## 文档真源与冲突处理

本 PRD **Amends** [历史全量审查 PRD](../PRD.md)的项目级导航和现状，不删除历史内容。患者作品展示仍见 [PORTFOLIO_PRD](../PORTFOLIO_PRD.md)，它的作品集目标不覆盖本次全项目梳理目标。

| 内容层级 | 唯一维护位置 |
|---|---|
| 全项目定位、范围、跨模块需求 | 本目录 [PRD](PRD.md)；状态 REVIEW |
| 患者专项详细行为 | [健康档案](../HEALTH_PROFILE_SPEC.md)、[手动随访](../FOLLOWUP_PLAN_SPEC.md)、[诊后 AI 候选](../POST_VISIT_AI_ACTIONS_SPEC.md)、[就医准备](../VISIT_PREPARATION_SPEC.md)、[独立报告](../PATIENT_REPORTS_REQUIREMENTS.md) |
| 医生端详细目标与既有裁决 | [DOCTOR_PRD](../DOCTOR_PRD.md)；整稿 REVIEW |
| 评测方法、分层与判分 | [EVALUATION_PROTOCOL](../EVALUATION_PROTOCOL.md) |
| 当前实现证据 | 本目录 [EVIDENCE](EVIDENCE.md)；过往成绩归各带日期验收文件 |
| 工程实现与启动 | [工程文档](../../engineering/architecture.md)、[项目 README](../../../README.md) |

发生冲突时：当前行为回查源码；目标行为追溯明确用户决定或获批规格；未裁决的冲突记录到 [DECISIONS](DECISIONS.md)，不得由阅读版或旧成绩单替代产品裁决。
