# 健康档案、随访计划、用药提醒：现状审查与验收

> 日期：2026-10-02（Asia/Hong_Kong）｜判定：REQUEST CHANGES
>
> 基线：`D:\CAI-Projects\medaxis` 当前未提交工作区。不是远程或生产环境快照。
> 本轮审查实际应用源码和相关回归；原型 HTML、历史验收记录不能替代应用闭环证据。
> 本轮未修改业务代码。下面的补充需求、时间门槛和状态设计是建议，不代表已经实现。

> 后续档案实现与验收入口见 [HEALTH_PROFILE_SPEC.md](./HEALTH_PROFILE_SPEC.md)。本文保留审查时基线，随访及提醒缺口不因档案补充自动关闭。
>
> 后续患者手动随访完善范围见 [FOLLOWUP_PLAN_SPEC.md](./FOLLOWUP_PLAN_SPEC.md)。本文缺陷为原审查快照；新链路与提醒未覆盖项以新规格及验证记录为准。

## 1. 完整性判断

**三个模块均有基础实现，但目前不能作为完整健康管理闭环验收。优先补齐数据流和失败处理，再扩充页面。**

| 模块 | 当前真实能力 | 阻止完整验收的缺口 |
|---|---|---|
| 健康档案 | 可读取并保存姓名、手机、性别、身高体重、过敏、慢病和当前用药；保存失败保留编辑状态；按当前用户隔离 | 档案没有自动进入已检查的初诊/诊后聊天上下文；年龄/出生日期契约缺失；清空与并发修订不完整 |
| 随访计划 | 可列出已有 CarePlan、兼容两种任务形状、提交完成并重拉列表 | 生产入口未连接 CarePlan 创建；任务接口可伪成功；JSONB 原地修改未触发变更检测；计划进度/生命周期与分页不完整 |
| 用药提醒 | 有事件、Celery ETA、周期扫描、领取及失败重试；页面包含发送状态、分页和患者自报确认；确认有行锁和幂等逻辑 | 创建源头未接通；频次/疗程未展开；邮件失败返回被忽略；缺少取消/计划变更联动及投递不确定性处理 |

健康档案的基础 CRUD 最接近可验收；随访首先要接通计划来源；用药提醒首先要修复发送结果与调度契约。

## 2. 优先修复的发现

P1 表示阻止相应功能完整验收；P2 表示完整性或可靠性补充。实现缺陷与未来产品建议分别列出。

### P1：档案提示与问诊实际数据流不一致

页面声明“过敏、慢病和用药会在问诊时作为参考”，见 [HealthProfilePage.tsx:186](../../frontend/src/patient/pages/HealthProfilePage.tsx#L186)。

当前聊天页面把历史用户消息拼成 `patient_history`，见 [ChatPage.tsx:234](../../frontend/src/components/ChatPage.tsx#L234)；流式初诊从请求读取它并传入诊断流程，见 [agents.py:1107](../../backend/app/api/v1/agents.py#L1107)、[agents.py:1361](../../backend/app/api/v1/agents.py#L1361)。诊后聊天使用 `_build_chat_context`，该函数读取诊断、问诊、化验和历史病例，未读取档案，见 [agents.py:374](../../backend/app/api/v1/agents.py#L374)。

已有 `_load_health_profile_context`，但它的调用仅位于没有生产调用点的 `_build_conversation_context` 中。对 `backend/app` 的调用点检索只找到这些定义及内部调用。

影响：患者新增过敏、慢病或用药后，这些档案项不会自动进入已检查的问诊路径。就医准备包读取过敏和用药是另一条路径，不能证明问诊接入。

建议：在已认证患者的活跃问诊/诊后上下文入口读取当前档案，保留来源、更新时间和未知状态；以模型请求上下文为验收证据。接通前修正页面承诺。

### P1：随访计划没有可用的生产创建闭环

`POST /agents/plan` 调 `PlanningAgent.plan()`，返回结果但不创建 CarePlan，见 [API:823](../../backend/app/api/v1/agents.py#L823)、[service:999](../../backend/app/services/agents.py#L999)。真正创建 CarePlan 的 `generate_care_plan()` 在 `backend/app` 中只查到定义，没有调用方，见 [service:1089](../../backend/app/services/agents.py#L1089)。医生计划入口明确返回 501，见 [doctor.py:230](../../backend/app/api/v1/doctor.py#L230)。

随访空状态却提示“完成一次问诊并保存记录后，这里会陆续出现需要关注的事项”，见 [FollowUpPage.tsx:125](../../frontend/src/patient/pages/FollowUpPage.tsx#L125)。当前生产路径不能兑现这句提示。

建议：明确谁创建、谁确认、何时生效，并把该入口接到统一的持久化计划服务。用药任务的来源与确认应独立标识；不把 AI 建议或患者自报反馈自动当成有效医嘱。

### P1：任务完成接口存在伪成功和持久化缺陷

`ack_task` 没有检查是否匹配任务；未知 task_id 仍提交并返回 `success: true`，见 [patient.py:871](../../backend/app/api/v1/patient.py#L871)。`check_in` 也有同样行为，并且列表形状的任务不会被更新，见 [patient.py:1017](../../backend/app/api/v1/patient.py#L1017)。

这两个接口原地修改普通 JSONB 对象后再赋回相同对象；模型没有相应的嵌套变更跟踪，见 [CarePlan.tasks:260](../../backend/app/models/agent.py#L260)。离线探针调用真实 ack 函数后观察到：内存状态为 completed，但 `inspect(plan).attrs.tasks.history.has_changes()` 为 false。这证明 ORM 没有识别该任务修改；本轮没有使用真实 PostgreSQL 验证重读结果。

建议：统一任务契约；未知 ID 返回明确错误；用新对象赋值或明确标记变更；同步服务器进度/完成状态。补充真实数据库的提交后新会话重读及并发更新测试。

### P1：频次、疗程、开始日期没有进入提醒调度

`generate_care_plan()` 的提示要求任务包含 `frequency/duration_days/start_date`，但每个 medication task 只生成一个当前时间后一小时的事件，见 [agents.py:1111](../../backend/app/services/agents.py#L1111)、[agents.py:1139](../../backend/app/services/agents.py#L1139)。这是尚未连接的生成服务中的缺陷，接通入口时必须一起修复。

例如合成规则“明天开始，每日 08:00 和 20:00，共 3 天”，应有 6 个对应时刻的事件；当前实现只生成 1 个事件。follow_up/self_check 任务也未在该方法中产生提醒。

建议：先确定提醒是否按每次执行发生；若是，则将明确时间、开始/结束日期和患者时区作为结构化输入。不能仅凭自由文本频次猜测排程。

### P1：邮件返回失败仍被标为已发送

`EmailService.send_email()` 以 `(success, error, log_id)` 返回结果；未配置邮件或 SMTP 失败可以返回 False，见 [email_service.py:183](../../backend/app/services/email_service.py#L183)、[email_service.py:244](../../backend/app/services/email_service.py#L244)。

`_send_reminder_email()` 忽略普通邮件和模板邮件的返回值，见 [monitoring.py:201](../../backend/app/tasks/monitoring.py#L201)；`_claim_and_send()` 只根据是否抛异常判断成功，随后将状态写为 sent，见 [monitoring.py:256](../../backend/app/tasks/monitoring.py#L256)。

离线探针保留真实发送封装和领取处理，只替换 EmailService 为返回 `(False, 'synthetic SMTP failure', None)`，观察到 `event_status=sent, retry_count=0`。现有重试测试仅覆盖发送封装直接抛异常，遗漏这一真实失败契约。

建议：消费 success/error/log_id，失败进入重试或失败终态并关联日志。`sent` 的含义应限定为通道已接受；需要“送达”的产品承诺时，另取通道回执或测试收件箱证据。

## 3. 其他缺口与补充建议

| 优先级 | 事实或缺口 | 建议 |
|---|---|---|
| P2 | User 有 age_years/age_months，没有 date_of_birth；档案 GET 使用 getattr 返回空出生日期，也不返回年龄。[user.py:51](../../backend/app/models/user.py#L51)、[patient.py:108](../../backend/app/api/v1/patient.py#L108) | 选择统一的年龄/出生日期真源；如支持儿童，明确月龄和字段范围 |
| P2 | 性别下拉提供空选项，但 schema 拒绝空字符串；身高体重禁止清空，且 API 只接受整数。[页面:271](../../frontend/src/patient/pages/HealthProfilePage.tsx#L271)、[schema:118](../../backend/app/api/v1/patient.py#L118) | 区分未提交、清空、未知；为小数体重和有效范围定义一致契约 |
| P2 | 页面提交整个档案快照；后端整体替换列表，没有版本冲突检查。[页面:89](../../frontend/src/patient/pages/HealthProfilePage.tsx#L89)、[API:152](../../backend/app/api/v1/patient.py#L152) | 避免旧客户端静默覆盖新过敏/用药；可使用版本条件和冲突提示 |
| P2 | 健康画像生成只存整段文本；页面 GET 不返回 AI 摘要，页面没有画像刷新入口。[service:1073](../../backend/app/services/agents.py#L1073) | AI 画像作为后续增强；展示时与患者填报分开，保留来源，不覆盖人工事实 |
| P2 | 服务端任务完成不联动计划 status/progress_percent；页面自行计算进度 | 由服务端统一生命周期，区分待确认、生效、暂停、完成、取消与到期 |
| P2 | 随访列表默认 10 条；前端无分页，列表可能遗漏旧计划。[patient.py:792](../../backend/app/api/v1/patient.py#L792)、[patient.ts:388](../../frontend/src/api/patient.ts#L388) | 补分页及总量/游标；测试 11 条以上 |
| P2 | 检索范围内没有计划/提醒取消写入路径；发送前也未检查关联计划状态 | 改药、停药、暂停/取消计划后，失效的未来事件必须被取消或拦截 |
| P2 | 邮件固定 UTC+8，页面使用设备本地时区；随访到期使用 UTC 日期 | 指定产品时区策略；时间存 UTC，展示及排程明确所用时区 |
| P2 | SMTP 成功与事件 sent 提交间存在崩溃窗口；过期 in_flight 会被重捞 | 普通 SMTP 不能仅靠数据库锁保证跨副作用的 exactly-once。明确至少一次及重复风险，或选择有幂等投递支持的通道；对投递结果不确定的状态建立对账规则 |
| P2 | 补捞任务每 30 分钟执行，单次查询 50 个到期事件。[celery_app.py:48](../../backend/app/tasks/celery_app.py#L48) | 先冻结延迟承诺，再按队列规模验证恢复耗时；不能把 ETA 正常路径当故障恢复证据 |

建议新增的产品信息：过敏/慢病的“有、无、未知”状态、更新时间和来源；用药的有效/停用状态及医嘱来源；随访的关联病例、执行时间、负责人和反馈入口。既往史/手术史/家族史可按目标人群补充，不作为修复现有闭环的前置工作。

“提醒已发送”“患者自报已服用”“专业人员确认”应分别记账。当前页面已有“已打卡（患者自报）”说明，本轮不将其误判为已经宣称医护确认。迟服、漏服、跳过原因、提醒偏好属于下一步产品补充。

## 4. 验收方式与通过标准

### 验收环境和证据

使用合成患者 A/B、独立的 PostgreSQL 测试库、独立 Redis/Celery 和本地邮件接收器或授权测试收件箱。不可指向现有业务库；后端数据库 fixture 会在结束时 drop_all，必须确认隔离库及测试安全规则。

每个用例保留：输入、对象 ID、API 请求/响应、提交后新数据库会话查询结果、页面结果；提醒还需保存事件和邮件日志/收件记录。不记录凭证或真实患者隐私。

生成服务可先用明确标记的模型替身验证流程，再单列真实模型结构化输出验证。替身、模拟邮件与真实依赖结果分别记账。

### 三个模块的必要用例

| ID | 操作/故障注入 | 通过标准 |
|---|---|---|
| H01 | 新患者读取空档案，填写基本信息、过敏、慢病、用药并保存；刷新、重登、清缓存重读 | API、新数据库会话和页面值一致；来源和未知状态明确 |
| H02 | 编辑小数体重、清空性别/数值、删除最后一条过敏或药物 | 按冻结契约保存或明确提示；不伪成功，不把未知转成“无” |
| H03 | 保存时断网/500，随后重试；取消编辑 | 失败无成功提示，草稿可继续处理；取消不写库 |
| H04 | 两客户端先读同版本，A 修改过敏，B 修改用药后保存 | 两项均保留，或 B 获得冲突提示；禁止静默覆盖 |
| H05 | 给 A 写入独特合成档案项，分别发起初诊和诊后聊天；再用 B 问诊 | 模型上下文包含 A 的正确档案来源；B 不含 A 信息；改档案后的新上下文符合版本规则 |
| F01 | 从产品实际入口创建并确认计划，重启服务后打开患者页 | 产生持久化 CarePlan、稳定任务 ID、来源关系和明确生效状态；不是预置数据库记录或孤立模型结果 |
| F02 | 完成已知任务、重复提交、提交未知 ID；提交列表/嵌套形状打卡 | 已知任务新会话重读仍完成；重复幂等；未知 ID 返回明确错误；格式按统一契约处理 |
| F03 | 两个并发请求完成不同任务；完成最后一项 | 两次修改均保留；服务器进度与计划状态、页面一致 |
| F04 | 暂停、取消、到期和来源计划变更后继续尝试执行 | 状态迁移符合产品规则；无失效计划继续触发的未来提醒 |
| F05 | 创建至少 11 条计划，切换分类和分页 | 全部可找到，无漏项/重复；失败显示错误，不能以空数据冒充成功 |
| F06 | 指标/复查任务填写值和备注、重新打开；输入非法值 | 数据带任务/时间/来源稳定保存；输入被校验；若纳入异常升级范围，还要验收通知、负责人和回执 |
| M01 | 合成用药规则：明天开始，每日 08:00/20:00，连续 3 天 | 生成 6 个确定时刻事件；今天不发；数量和时间与规则逐项一致 |
| M02 | 事件到时，真实 worker 和选定邮件通道执行 | 事件、通道日志及收件记录关联同一逻辑提醒；区分通道接受、送达和患者自报 |
| M03 | SMTP 抛异常、SMTP 返回 False、未配置邮件三类失败 | 均不得标 sent；重试递增，达到上限为 failed；页面和日志一致 |
| M04 | ETA 和 sweep 同时领取同一事件；重复投递 | 正常并发只执行一次外部发送；已处理事件再次执行无副作用 |
| M05 | 到期前停 worker、入队失败、领取后崩溃、SMTP 成功后提交前崩溃 | 恢复达到冻结门槛；对发送结果不确定的崩溃窗口按明示策略处理，不虚称 exactly-once |
| M06 | 修改/取消原计划或停用药物，再运行 ETA/sweep | 不再发送旧未来提醒，保留历史记录及可解释状态 |
| M07 | 确认成功后刷新/重登，重复点击；确认接口返回 409/500 | 自报状态持久且幂等；失败不打卡；不把未确认、未送达统计为已服用 |
| M08 | 51 条以上同一时刻事件逐页加载；跨时区与跨日查看 | 稳定游标无漏项/重复；按同一时区策略显示计划时间和到期日 |
| X01 | A/B 跨账号读取、确认、打卡；未登录/过期 token | 未登录被拒，跨账号不可读写；数据库与通知无他人数据 |

正常发送延迟建议先以“指定时刻后 60 秒内由测试通道接收”为小规模工程门槛，worker 恢复后建议 5 分钟内完成补捞；这是待冻结的建议值，当前 30 分钟 sweep 不满足后者。若产品接受更长延迟，必须在验收前明确，而不是看完结果再修改阈值。

### 分阶段门禁

1. **数据契约门禁**：档案读写、计划创建、任务完成的新会话重读、权限与失败语义全部通过。
2. **最小链路门禁**：一个真实产品入口创建计划 → 生成确定时刻事件 → worker 发信 → 页面显示 → 患者自报 → 重登恢复；各阶段逐项对账。
3. **可靠性门禁**：并发、重复、取消、重启、发送失败、时区和分页用例通过；发送不确定性已有明示策略。

P1 未关闭前不得宣称模块完整。三个门禁通过才可称限定范围工程闭环通过；真实模型内容质量、真实用户可用性和医学内容专业评审另行记录。

## 5. 本轮验证证据与边界

| 命令（相应工作目录） | exit code | 本轮结果 / 证明范围 |
|---|---|---|
| `node --experimental-strip-types --test tests/patientProfile.test.mjs tests/patientReminders.test.mjs`（frontend） | 0 | 6 passed；API helper 契约和错误传播，不证明页面/数据库/调度 |
| `.\node_modules\.bin\tsc.cmd -p tsconfig.app.json --noEmit`（frontend） | 0 | 应用源码 TypeScript 静态检查通过，不证明功能闭环 |
| `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_patient_reminders.py tests/test_monitoring_reminder_retry.py`（backend，使用下面合成进程环境） | 0 | 14 passed；fake session 状态/游标及局部查询测试；未连接 PostgreSQL、Redis 或 SMTP |
| `.\backend\.venv\Scripts\python.exe .\.ai\tasks\2026-10-02-health-followup-medication-review\review_probes.py`（仓库根） | 0 | 6 组缺陷观察成立：未知 ack、未知 check-in、JSONB 未变脏、列表打卡不更新、SMTP False 被标 sent、空性别被拒；这是缺陷复现成功，不是业务验收通过 |

2026-10-02 局部测试的历史进程配置（PowerShell；全为合成值，不可用于数据库集成验收）。当前复跑数据库 fixture 须使用 `medaxis_test_*`、三个一致 URL 和显式清表确认，见[当前后端说明](../engineering/backend.md#本地运行与测试)；不能直接沿用下面的历史库名：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://review:review@127.0.0.1:1/medaxis_pytest_module_review'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:ASYNC_DATABASE_URL = $env:TEST_DATABASE_URL
$env:REDIS_URL = 'redis://127.0.0.1:1/0'
$env:PYTHONDONTWRITEBYTECODE = '1'
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests/test_patient_reminders.py tests/test_monitoring_reminder_retry.py
```

探针源码和输出位于本机 `.ai/tasks/2026-10-02-health-followup-medication-review/` 内的 `review_probes.py`、`probe-results.json`，它们不是公开可下载附件。`.ai` 不随项目文档分发；后续修复应将相关场景转为正式回归，并移除“预期缺陷”的探针断言。

执行回退：首次后端测试使用 SQLite DSN，被 Settings 的 PostgresDsn 校验拒绝（exit 1），改为上述合成 PostgreSQL 格式的进程环境后通过；未改环境文件、未开库。探针首次网络保护覆盖到了 Windows asyncio 内部 socketpair（exit 1），将保护移到事件循环初始化后再次运行成功。初次根配置 `tsc --noEmit` 返回 0，但根 tsconfig 没有源码文件；补核后运行表中应用配置命令，实际源码检查返回 0。

未执行：真实数据库事务及并发集成、真实 Celery/Redis、SMTP 投递/收件、浏览器 E2E、真实模型质量和医学内容验收。既有测试通过不否定已复现缺陷，也不能外推为这些场景通过。

## 6. 实施顺序与审查自检

建议顺序：修复伪成功和任务持久化 → 定义并接通计划来源/生效 → 实现明确时间排程及失效取消 → 接入档案上下文 → 收口可靠性验收 → 再补画像、迟服/漏服和异常升级。

最可能失败的五点及本轮处理：

1. 把未连接的生成服务当成现有用户能力：已明确生产调用断点及潜在排程缺陷。
2. 把 fake session 的通过当成数据库持久化：已限定测试层级并单列新会话重读验收。
3. 将 EmailService 的返回失败和抛异常混淆：保留真实封装执行，并复现 False 返回路径。
4. 凭数据库领取锁承诺 SMTP exactly-once：已指出外部副作用后的崩溃窗口，要求明确投递保证。
5. 将患者自报、AI 建议当成医嘱或真实服药：已要求来源与状态分离；本轮未做临床结论。

本轮新增审查文档、本地探针和输出，并在 docs/README.md 增加一行索引；没有修改业务实现或现有环境。需要撤除时只处理这些本轮新增文件和索引行，不回滚原有未提交工作区。
