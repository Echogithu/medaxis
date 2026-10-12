# 患者随访计划

本轮范围由用户选择：先完善患者手动录入与确认。页面入口 `/followups`。

## 行为合同

- 患者可手动录入一个计划，包含 1–20 项复查或自测任务；每项代表一次执行，不解释自由文本周期、不自动展开用药频次。
- 名称、起止日期与每项内容/日期必填；结束不能早于开始，任务日期必须处于计划区间。说明与自测单位可选。
- 可关联患者本人的病历。来源显示“患者录入”，确认表示患者准备执行，不表示医生核验。历史计划显示“来源未核验”，不补造确认时间。
- 保存为待确认；待确认可编辑或取消。执行内容需要核对后确认。
- 生效后可记录完成、暂停或取消；暂停可恢复或取消。完成或取消为终态，修改执行内容需取消后新建。全部任务完成时自动完成计划，服务端同步进度与完成时间。
- 任务完成可附备注，自测可附一个有限数值（包括 0）。只记录患者自报，不做单位转换、医学阈值判断或异常升级。
- 同一任务的重复完成保留第一次的时间、数值与备注；不同任务并发完成串行合并，不相互覆盖。开始日期之前、待确认、暂停、到期、取消时禁止新增执行记录。
- 按北京时间 UTC+8 判断日期；结束日当天仍可执行，下一天到期。有效状态与任务逾期分别展示。任务未到计划日期也允许患者自报提前完成。
- 新建使用稳定请求 ID；响应丢失后原内容重试只创建一条。同一 ID 的不同内容被拒绝。编辑、状态操作使用版本条件，冲突提示重新读取。失败保持对话框及填写；主动“放弃当前填写并重新加载”会丢弃填写。
- 列表有状态筛选与游标分页。请求失败显示错误；首屏失败不冒充空计划，加载下一页失败保留已加载列表。

## 提醒联动边界

本轮手动计划提供页面执行管理，不自动发送复查邮件或生成药物提醒。提醒偏好、按执行时刻创建事件与真实通道验收留在提醒模块。

对已有关联事件：暂停将 pending 改为 paused；恢复只让未来 paused 回到 pending，暂停期间到时的事件取消；取消及任务/计划完成取消尚未发送的相关事件。发送任务也在发送前核对关联计划及患者，阻止漏网失效事件或过早执行。

已开始对外发送的提醒不能召回。SMTP 被接受与记录 sent 之间的崩溃窗口仍可能重复发送，当前不能承诺 exactly-once。已发送或已自报记录保留历史。邮件服务返回 False 进入失败重试，不能标为发送成功。

## 数据与接口

复用 CarePlan 和 MonitoringEvent，不新增数据库列。任务保存为 `tasks={tasks: [...], metadata: {...}}`；metadata 保存来源、病历关联快照、确认时间、更新时间、版本及创建请求指纹。历史数组/嵌套对象都归一化读取；缺失或重复任务 ID 产生稳定标识，首次修改以新 JSONB 对象持久化。

| 接口（`/api/v1/patient` 前缀） | 合同 |
|---|---|
| POST `/care-plans` | `request_id`、名称/说明、病历 ID、日期、复查/自测任务；201，重复请求返回同一计划 |
| GET `/care-plans` | 默认保留列表返回；`include_page=true` 返回 items/next_cursor，可带 status、limit、cursor_at/cursor_id；按创建时间和 ID 稳定排序 |
| GET `/care-plans/{id}` | 本人计划详情，返回归一化任务、来源、版本、服务端进度与 can_execute |
| PATCH `/care-plans/{id}` | 待确认内容修订及 expected_revision；不允许直接改来源/确认状态 |
| POST `/care-plans/{id}/actions` | confirm/pause/resume/cancel，expected_revision；同一成功操作重试幂等 |
| POST `/care-plans/{id}/ack?task_id=...` | 兼容既有完成入口，统一行锁与执行逻辑 |
| POST `/check-in` | plan_id、task_id、可选有限 value/notes，返回任务结果及最新计划 |

仅患者本人可使用；未登录 401、非患者 403、他人或未知计划/任务 404、输入不合法 422、状态或版本冲突 409。创建/编辑来源字段由服务端写入，输入多余字段被拒绝。

## 验收与运行边界

从 backend 运行 `.\.venv\Scripts\python.exe -m tests.followup_chain_isolated`。要求已有 `pgvector/pgvector:pg17` 镜像、前端 node_modules、Edge 及可导入 Playwright 的 Python；可用 PROFILE_BROWSER_PYTHON 指定浏览器运行时。

脚本仅创建本次独立容器、测试/演示数据库及 API/Vite 进程，结束后清理自己的资源。真实 PostgreSQL/API 验证来源、幂等、状态、持久化重读、旧任务形状、并发、分页与本人隔离；Edge 使用真实隔离 API 验证页面，模型与邮件不作为真实依赖验收。结果记录在 `.ai/tasks/2026-10-02-followup-plan-chain/`。

frontend 定向检查：`node --test tests/patientCarePlans.test.mjs tests/patientProfile.test.mjs tests/patientReminders.test.mjs`、`.\node_modules\.bin\tsc.cmd -p tsconfig.app.json --noEmit`、`npm run build`。

本机真人验收清单位于 `.claude/manual-test-followup-plan-chain.md`，该文件不随公开克隆分发；行为和验收入口见本页。现有业务服务未升级或重启，业务数据库未写入。部署时先确认现有迁移 head（含上一轮档案迁移），再更新 API/前端，验证真实患者登录与旧计划；本轮无新增迁移。

恢复时按本轮差异回退代码，保留元数据和执行记录；不能整仓覆盖已有未提交改动或清除新计划。修改前文件保存在任务目录 backups；前后端需配套恢复，避免旧客户端把暂停/取消误认为可执行。
