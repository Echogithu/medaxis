# 当前待处理问题摘要

> 静态核对日期：**2026-10-06**。本页只整理当前工作区代码与已有验证记录，不是开发排期，也不表示本轮运行了应用测试。历史缺陷与原编号见[审查型 PRD](./PRD.md)。

## 当前仍需处理或补证据

| 优先级建议 | 问题 | 当前证据与边界 |
|---|---|---|
| P0 | 医生认证门禁与真实数据展示 | [doctor.py](../../backend/app/api/v1/doctor.py) 已检查角色和分配归属，但 `_require_doctor` 未检查 `is_verified`；[详情页](../../frontend/src/doctor/pages/CaseDetailPage.tsx) 仍混入 MOCK_CASE。医生计划接口返回 501，评论与患者接收未形成完整路径。 |
| P1 | 真实模型的完整问诊验收 | 两次短对话证明模型可回答与额度持久化，不能替代首轮→补问→报告→保存→恢复。10 个固定案例仍未完整验收，见[冒烟题集](../../evals/patient-smoke/README.md)。 |
| P1 | 新报告中心部署与最终验收 | 归档、取字、核对、引用、去重和回收站代码已接入；当前本机演示尚缺新版迁移。真实拍照 OCR、真实模型整理、Linux 部署及完整链路需分别验证，见[报告现状](./PATIENT_REPORTS_REQUIREMENTS.md)。 |
| P1 | 提醒送达与故障恢复 | 患者手动计划和诊后 AI 安排已有实现；不再描述为“没有创建 CarePlan 的路径”。真实模型提取质量、邮件送达、长期队列运行及重启/重复投递仍需验收，见[随访](./FOLLOWUP_PLAN_SPEC.md)和[诊后安排](./POST_VISIT_AI_ACTIONS_SPEC.md)。 |
| P1 | 旧聊天附件的原件外发边界 | [documents.py](../../backend/app/api/v1/documents.py) 仍可能发送原图或文件；新报告中心的文字预览同意不能覆盖旧入口。演示只使用合成资料。 |
| P1 | 撤销与全量权限审计 | [身份依赖](../../backend/app/api/deps.py) 的 Redis blacklist 查询异常仍走 fail-open。专用演示保护不代替全应用安全审计。 |

## 已修复的历史问题

公开注册管理员、医生病例角色/归属、解析结果归属、解析任务内存状态、旧病例字段和医生审核响应问题已不应照旧作为待修复清单；对应历史记录保留在 PRD 与[路线图快照](./CLOSURE_ROADMAP.md)。

旧 PRD 的 165 条 TypeScript 错误不是当前结果；2026-10-06 的类型检查与构建通过记录见[演示说明](../INTERVIEW_DEMO.md)。构建成功不证明所有页面行为、全仓 lint 或生产部署通过。

DoctorAgent、独立 KnowledgeAgent、MCP、GraphRAG、Android 和完整医生协作仍不能列为已交付能力。个人贡献、真实用户价值与医疗内容专业验证也不能由工程测试代替。
