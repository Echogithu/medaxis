# 待处理问题摘要

> 静态核对日期：**2026-09-24**。本页是高优先级风险摘要，不是已批准排期；完整范围、证据和验收要求以[审查型 PRD](./PRD.md)为准。本轮未运行应用测试或生产验证。
>
> **2026-09-27 更新**：本页部分条目（注册角色、病例/解析结果归属校验、解析任务持久化）已在当前源码修复。按链路排序的最新计划见[业务链路闭环路线图](./CLOSURE_ROADMAP.md)。

## 需要优先处理

| 优先级 | 问题 | 当前证据与边界 |
|---|---|---|
| P0 | 限制公开注册可授予的角色 | 注册 schema 接受管理员角色且注册入口直接使用请求角色；应通过授权边界和拒绝用例修复。见 [R01](./PRD.md) 与 [auth API](../../backend/app/api/v1/auth.py)。 |
| P0 | 补齐病例与解析结果的角色/所有权校验 | 医生详情和文档结果接口存在权限缺口；登录或 task ID 不能代替资源所有权校验。见 [R02](./PRD.md)、[doctor API](../../backend/app/api/v1/doctor.py)、[documents API](../../backend/app/api/v1/documents.py)。 |
| P0 | 隔离演示数据并修正失败反馈 | 医生详情、评论和计划路径仍存在模拟数据或失败时展示成功的风险。见 [R03](./PRD.md) 与 [CaseDetailPage](../../frontend/src/doctor/pages/CaseDetailPage.tsx)。 |
| P1 | 对齐前后端数据契约并恢复可运行检查 | 病例、随访、模型配置等模块仍有字段/类型差异。PRD 记录的 165 条 TypeScript 错误是前次审查结果，当前数量需重跑确认。见 [R04/R05](./PRD.md)。 |
| P1 | 让解析任务状态跨重启、跨 worker 可恢复 | documents API 当前在进程内字典保存任务状态；异步状态应使用共享持久化机制或明确单 worker 限制。见 [documents API](../../backend/app/api/v1/documents.py)。 |
| P1 | 闭合随访、提醒与监测失败路径 | 目前有页面、API 和定时任务代码，但并未证明创建、发送、确认、重试和重启恢复构成可用闭环。见 [患者 API](../../backend/app/api/v1/patient.py) 与 [Celery 配置](../../backend/app/tasks/celery_app.py)。 |

## 与旧 TODO 的对照

旧列表中的 patientHistory、SSE 解析复用和医生页面“全为空壳”等描述已不准确：当前代码已有相关实现，但聊天错误透传和医生端模拟数据问题仍在。provider 配置也支持多供应商选择；缺少的是跨供应商故障切换，不能继续描述成“只有单 provider”。

DoctorAgent、KnowledgeAgent、MCP、GraphRAG、WebSocket 和 Android 仍属于待规划能力，不应作为当前产品功能宣传。实现顺序和需求优先级需要先经过 PRD 评审。
