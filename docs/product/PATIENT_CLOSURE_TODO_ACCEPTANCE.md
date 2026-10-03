# 患者端闭环审查、执行清单与验收合同

初始审查日期：2026-09-27；状态核对：2026-09-28。状态：**REVIEW_COMPLETE / IMPLEMENTATION_IN_PROGRESS**。

审查基线：本地 HEAD `ec3220550ec6fbb1f9e4139c2054c6ecf410f750` 加审查时工作区。原有未提交文件为 `docs/README.md`、`docs/product/todos.md`、`docs/product/CLOSURE_ROADMAP.md`，本次不覆盖它们。用户指定的 `CLOSURE/_ROADMAP.md` 不存在，实际审查的是 [CLOSURE_ROADMAP.md](./CLOSURE_ROADMAP.md)。首次审查阶段仅新增本文，未修改业务代码或操作业务数据库；后续执行结果及代码状态按 T00–T16 分项记录。

## 1. 结论与完成边界

**患者端已有可复用的演示主线，但尚不能验收为可靠的真实患者业务闭环。**

| 层级 | 当前结论 | 完成所需条件 |
|---|---|---|
| A：患者自助主线 | 历史合成演示通过；真实模型待验收，身份迁移、错误反馈、旧病例可达性仍有缺口 | 问诊→补问→报告→唯一病例→准备摘要→患者自报→清缓存重登恢复，真实依赖及失败路径通过 |
| B：材料参与主线 | 已有持久解析、归属检查与回归；真实上传/解析组合未验收 | 前端上传→worker→解析→原会话→原病例→重启恢复 |
| C：医患与随访 | 未闭环 | 授权医生复核→患者看到意见→有效计划→提醒→患者反馈→异常接收与回执 |
| D：个性化科室建议、完整云端聊天 | 未完成，属于独立扩展 | 明确范围、审核依据及各自验收；不得作为 A 的隐含完成项 |

A 不要求平台医生签署；C 不能用患者自报或院外就医代替。中性科室目录不是个性化推荐，更不是预约。真实模型工程验收也不等于医学内容专业验收。

已实现的病例保存、准备包、反馈与归属控制应复用，只补缺口和证明。历史 [闭环计划](./PATIENT_DEMO_CLOSURE_PLAN.md) 与 [独立审查](./PATIENT_DEMO_CLOSURE_REVIEW.md) 仅证明当时覆盖的场景，后者特别指出 Redis 锁也有替身、测试库清表及证据脚本硬编码问题。本次不继承其“92 passed”为本轮结果。

## 2. 对原路线图的审查意见

总体方向成立，但尚不足以直接交给执行模型：需要拆出患者任务、先后依赖、可复验反例和证据要求。

1. **漏列确定的提醒请求错误。** [MedicationReminderPage.tsx:37](../../frontend/src/patient/pages/MedicationReminderPage.tsx#L37) 请求 `limit=100`；[patient.py:879](../../backend/app/api/v1/patient.py#L879) 限制 `le=50`。按当前接口契约会返回 422，前端又将非 2xx 变为空数组。应优先修，不只是修确认按钮。
2. **漏列旧病例不可达。** [patient.py:188](../../backend/app/api/v1/patient.py#L188) 默认每页 10 条；[patient.ts:184](../../frontend/src/api/patient.ts#L184) 不传页码；[PatientCasesPage.tsx:90](../../frontend/src/patient/pages/PatientCasesPage.tsx#L90) 要求指定 ID 属于当前列表。第 11 条以后的病例无分页入口，旧链接也被页面拒绝。
3. **访客配额修复范围不足。** 除 SSE 的 999 外，后台默认键为 `auth.guest_max_messages`（[admin.py:92](../../backend/app/api/v1/admin.py#L92)），服务读取 `guest.max_messages`（[config.py:112](../../backend/app/services/config.py#L112)）；在 `backend/app` 搜索未发现 `message_count` 的实际扣减/请求门禁。仅替换常量无法形成配额约束。
4. **“患者端不返回医生意见”需限定。** 通用 [medical_cases.py:149](../../backend/app/api/v1/medical_cases.py#L149) 配合 `_can_access_case` 已允许患者读取自己的详情，响应 schema 有医生字段。患者专用列表/recovery 与患者页面未接通展示，才是缺口；不要重复建设整个详情接口。
5. **运行态数字缺日期和环境。** provider `0/0` 来自历史独立审查，本次未查询当前数据库；不能写成当前已证实的配置状态。
6. **优先级混合两种产品范围。** [聚焦 PRD](./PORTFOLIO_PRD.md) 的作品主线允许医生闭环后置；原路线图是全项目目标。本文用 A/B/C/D 分别验收，延期不等于需求取消。
7. **验收语言过宽。** “无漏发/重复”需要给定故障窗口、计时与重试策略；发送端接受不等于患者收到/已读。本文要求分别对账，不承诺外部邮件 exactly-once。
8. **测试默认 PostgreSQL 仍不够安全。** 当前 [conftest.py:31](../../backend/tests/conftest.py#L31) 结束时 `drop_all`；首先防止误连业务库，再做数据库选择与回归。

## 3. 执行约定与依赖

任务状态只使用 `TODO / IN_PROGRESS / BLOCKED / IMPLEMENTED_NOT_VERIFIED / PASS / FAIL`。“验证”类先复跑，只有失败才改业务代码。文中的 P0 是患者闭环阻断优先级，不是统一安全漏洞评级。

建议顺序：**T00 → T01–T05 → T06–T09 → A/B 验收 → T10 → T11–T14 → C 验收**。T15/T16 单独排期。可独立探索，但多个任务触及 `patient.py`、`api/patient.ts` 时串行整合。

| ID | 优先级 / 类型 | 待办 | 依赖 | 状态 |
|---|---|---|---|---|
| T00 | P0 / 验证底座 | 隔离库、证据脚本及复跑说明 | 无 | PASS（2026-09-28；核对既有证据，未重跑） |
| T01 | P0 / 缺陷 | 提醒列表、确认、统计与错误态 | 无；后端集成验收依赖 T00 | IMPLEMENTED_NOT_VERIFIED |
| T02 | P0 / 缺陷 | 旧病例分页和直达恢复 | T00 | PASS |
| T03 | P0 / 缺陷 | 注册访客迁移与失败重试 | T00 | IMPLEMENTED_NOT_VERIFIED |
| T04 | P0 / 缺陷 | 访客配额配置、扣减和并发门禁 | T00，先冻结计费动作语义 | PASS |
| T05 | P0 / 缺陷 | 档案字段往返及保存失败恢复 | T00 | PASS |
| T06 | P0 / 验证与错误处理 | 真实模型主线、稳定错误码 | T00、T02、T03 | BLOCKED |
| T07 | P1 / 组合验证 | 真实上传解析、关联及重启恢复 | T00、可用解析依赖 | BLOCKED |
| T08 | P0 / 验证 | 并发保存、跨患者隔离、恢复 | T00；T06 提供真实主线证据 | IMPLEMENTED_NOT_VERIFIED |
| T09 | P0 / 验证与语义补齐 | 摘要未知/矛盾/版本与自报边界 | T00、T06 | IMPLEMENTED_NOT_VERIFIED |
| T10 | P1 / 跨端功能 | 医生复核结果到达患者 | D1；测试依赖 T00 | TODO |
| T11 | P1 / 功能 | 生成、批准、生效、取消计划 | T10、D2 | TODO |
| T12 | P1 / 缺陷与功能 | 任务确认、数值反馈、进度持久化 | T11；可提前用合成夹具测 API | TODO |
| T13 | P1 / 功能 | 按计划排程、发送和终态恢复 | T01、T11、T12 | TODO |
| T14 | P1 / 功能 | 异常事件、负责医生通知与回执 | T10–T13、D3 | TODO |
| T15 | P2 / 条件扩展 | 有审核依据的科室建议 | D4 | TODO |
| T16 | P2 / 条件扩展 | 患者云端聊天与健康画像 | D5 | TODO |

### T00 — 安全、可复跑的验证底座

- **现状/位置：** `backend/tests/conftest.py` 测试退出会清测试表；因此测试入口必须在建表前识别并限制目标。合成服务默认使用 Redis 替身；真实 Redis 只允许显式选择 loopback URL。参考独立审查，执行前复核行号。
- **实施：** 使用专用一次性 PostgreSQL 测试库；启动测试前核验测试库标识、显式允许标志及与演示/业务库的隔离，不打印凭据。错误配置应在建表/清表前拒绝。演示库另建、保留。结果动态读取迁移版本与对象关联，列全替身清单。
- **验收：** 缺少/错误数据库配置时拒绝运行且无 DDL；正确空库能跑定向与全量回归；结束后业务/演示库未改变。E2E 结果中的 head 等于实际查询值，`case.source_session_id` 等于本轮会话。并发锁验收必须用真实 Redis。
- **证据：** 环境标识、脱敏库名、配置拒绝测试、命令/退出码、动态对账 JSON；不得仅贴“数据库连接成功”。
- **当前实现：** `tests/database_safety.py` 由 `conftest.py` 在 test engine 建表前校验所有 DB URL 一致；仅允许内存 SQLite，或带 `MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB=1` 的 `postgresql+asyncpg`、`medaxis_test_` 库名。合成 E2E 与 demo server 校验 loopback PostgreSQL 专用库。合成 server 默认用锁替身；`DEMO_REDIS_LOCK_MODE=redis` 仅接受 loopback Redis。模块只能经 `python -m tests.patient_demo_server` 启动，导入与直接脚本入口均在加载应用前拒绝。E2E 动态读取源 Alembic head 并与数据库版本对账，另核对 case/source session/preparation/feedback 的实际关系。
- **既有 T00 验收记录（2026-09-28；本 Goal 未重跑）：** 在独立测试库 `medaxis_test_closure_3ce15962` 运行全量后端 `backend/tests`，187 passed、179 warnings、204.03 秒、exit 0。最终同轮 E2E 命令 `& 'D:\CAI-Projects\medaxis\backend\.venv\Scripts\python.exe' '.ai\tasks\2026-09-28-patient-closure-execution\run_t00_testdb_e2e.py'` exit 0；浏览器运行时为 Microsoft Edge headless / Playwright 1.58.0。测试只使用合成患者和确定性 LLM 替身。
- **同轮对账：** `.ai/tasks/patient-closure-evidence/t00-testdb-e2e-20260928T033515Z.json` 记录 API 就绪检查、仓库与数据库 migration head `b2c3d4e5f6a7`、浏览器/API/SQL 同一 `case_id` 与 `source_session_id`、患者 owner、structured report、preparation、feedback 及其外键关联。真实 Redis `MONITOR` 捕获同一 source session 的 `EXISTS diag_lock:<id>` 和 `SET diag_lock:<id> 1 NX EX 60`。重登恢复成功、跨患者读取返回 404、页面错误数为 0。
- **安全与清理：** 使用指定库中新建的临时非超级用户；迁移前 public 表为 0，清理前 25 张，清理后 0，临时角色不存在。演示库与业务库未用作测试目标，测试容器与 API/worker 网络隔离。首次执行曾把 schema CREATE 误授予 `postgres.public`；按用户授权撤销该误授并删除临时角色，最终运行只向目标测试库授予 schema 权限，未留残余。
- **独立复核与边界：** 全新 `gpt-6-sol / medium` 只读复核判定 T00 **PASS**。复核的两项 P2 可追溯性建议是单独留存全量回归原始 stdout，以及为错误 DB 配置拒绝路径保存独立运行 artifact；已有安全校验单测与 fixture 建表前校验支持当前结论，不构成本轮阻断。此证据验证的是确定性替身下的患者端持久化与恢复，不验证真实模型质量或临床安全。

### T01 — 提醒页先恢复真实可用

- **现状/位置：** `frontend/src/patient/pages/MedicationReminderPage.tsx:33–65`、`frontend/src/api/patient.ts:315–326`、`backend/app/api/v1/patient.py:874–926,976`。`PATCH .../acknowledge` 是存在的路由，API helper 的 `POST .../ack` 才是不匹配；页面没有检查 HTTP 失败。默认 pending 与侧栏 sent 计数也不一致。
- **实施：** 合并到统一 API helper；采用最多 50 条的 `(scheduled_at, id)` 游标分页与唯一排序；明确区分待发送、发送中、待确认、已确认、失败/取消；加载失败不可当空列表。确认成功后以服务端结果更新；只允许已发送提醒打卡，提前确认返回冲突。发送失败最多 3 次，终次失败持久化为 `failed`，旧 NULL 重试计数按 0 处理。空记录不显示“依从性 100%”；展示“当前已加载记录”中的患者自报率，分母仅含已送达提醒。提示患者在档案录入药物不会自动创建提醒。
- **验收：** 默认进入页无 422；0/1/51 条数据可完整浏览，同一时间戳下依靠 ID 稳定续页；sent 提醒可见且计数相符；401/422/500/断网均显示错误和重试。确认失败不改为已确认；成功后新浏览器会话重读一致；重复确认幂等；pending/in_flight/failed/cancelled 的确认拒绝，不冒充已服药。第三次发送失败进入终态，NULL retry_count 可正常被扫描重试。空分母显示无数据。
- **当前状态：** `IMPLEMENTED_NOT_VERIFIED`。后端 fake-session 路由测试、内存 SQLite 重试筛选测试及前端 API 测试覆盖状态契约、cursor、错误传播与 NULL retry_count；`31` 项后端定向测试、`16` 项前端测试、TypeScript 检查、定向 ESLint 与 Vite build 通过。独立 `gpt-6-sol / medium` 复核未发现静态阻断；PostgreSQL 事务/行锁与并发、浏览器 0/1/51 交互尚未运行，不能标记为 PASS。
- **新增真实浏览器抽验：** 同轮真实 API/PostgreSQL 上，新合成患者的提醒列表返回 HTTP 200、`items=[]`，页面显示“暂无用药提醒”及“暂无已送达提醒”状态，无页面错误（证据见最新 `patient-demo-browser-*.json`）。这仅覆盖 0 条数据；1 条/51 条分页、同时间戳 tie-break、已发送确认和错误恢复仍未在真实浏览器/数据库验收，T01 继续为 `IMPLEMENTED_NOT_VERIFIED`。

- **本轮 UI-only 浏览器回归（2026-09-28）：** Playwright 在本地患者页用 `window.fetch` 拦截 API，验证首屏 50 条、同时间戳 ID 游标加载第 51 条、模拟确认 HTTP 500 后保留待确认、重试成功后显示 1/51；无页面错误，外部字体域被阻断。证据 `.ai/tasks/patient-closure-evidence/patient-reminder-ui-mock-1790551011720.json` 标为 `PASS_UI_ONLY`、`databaseTouched=false`。它不访问真实 API/数据库，不能替代正向提醒数据、持久化和邮件重试验收；T01 继续为 `IMPLEMENTED_NOT_VERIFIED`。
### T02 — 患者能找回所有病例

- **现状/位置：** `patient.py:185–213`、`api/patient.ts:184`、`PatientCasesPage.tsx:88–103`。
- **实施：** 分页/加载更多；指定病例 ID 不依赖首页成员身份判断，由受保护的 recovery 接口鉴权。保留现有 A/B 切换隔离。
- **验收：** 同患者创建 11 条以上记录，第 11 条可从列表及保存链接打开；清缓存重登后能恢复该病例及准备/反馈；不存在 ID 和其他患者 ID 拒绝且不残留上一病例；慢请求反序不能覆盖最后选择。不要用把 limit 调大替代分页。
- **实施：** 后端病例列表支持有界分页和稳定排序；前端提供加载更多、ID 去重。URL `case_id` 是显式选择来源，直接 recovery 不要求病例出现在首页列表；无该参数时回到已加载列表首条，点选通过浏览器历史更新 URL。详情失败时清除旧病例内容，过期响应不得覆盖当前选择。
- **本轮验证：** 后端 `tests/test_database_safety.py`、`tests/test_patient_reminders.py`、`tests/test_monitoring_reminder_retry.py`、`tests/test_patient_cases.py` 合计 **33 passed**；前端 `npm test` **20 passed**；`npx tsc --noEmit -p tsconfig.app.json`、定向 ESLint、`npm run build`、`git diff --check` 均 exit 0。Vite 有现存的大 chunk 警告。
- **本轮真实浏览器验收：** 最新合成 E2E 通过真实认证/API/PostgreSQL 创建 10 条额外病例，使原会话病例成为第 11 条；列表第 1 页 10 条、第 2 页 1 条，患者点击第 11 条恢复同一报告；清浏览器状态重登后用 `case_id` 深链直接恢复仍在第 1 页之外的原病例。访问不存在病例和第二位患者的病例均返回 404，且页面确认清掉此前报告正文与病例标题。浏览器人为延迟一个病例 recovery 响应，切换到另一病例后迟到响应未覆盖当前 URL/详情；无浏览器错误。机器结果见 `.ai/tasks/patient-closure-evidence/patient-demo-browser-2026-09-27T21-48-44.330Z.json`。
- **独立复核与当前状态：** 最新 `gpt-6-sol / medium` 独立复核确认本次 evidence artifact 为目录内最新 run，检查了分页、重登深链、missing/foreign 404 后 UI 清除旧详情、owner-scoped recovery 查询及慢响应竞争，并未发现 P0/P1/P2；T02 标记 `PASS`。边界仍是 synthetic LLM 替身不代表真实模型/临床内容验证，底层过期 HTTP 请求虽未取消，其结果已被前端丢弃，不影响当前病例选择。

### T03 — 访客注册后资产可迁移

- **现状/位置：** `auth/RegisterPage.tsx:167–174` 注册后直接跳转；`LoginPage.tsx:96–103` 已调用迁移；`api/agent.ts:322`、`backend/app/api/v1/auth.py:644` 有现成接口。
- **实施：** 注册成功后复用双身份迁移；处理结果与本地历史身份切换。失败保留访客凭证/可重试入口，不声称数据已保存；成功才清理相应访客状态。服务器已修双 token 的部分不重写。
- **验收：** 访客有已完成问诊和已上传材料，注册后会话、可保存病例、材料归属新患者且可从病例恢复；重复迁移不复制记录；模拟迁移 500 后重试成功；过期/他人访客凭证被拒。对迁移中未完成问诊是否继续、访客报告如何生成病例给出明确契约并验证，不能只断言迁移接口被调用。
- **实施结果：** 当前注册 API 不返回用户 token，患者实际流程为“注册→登录→迁移”；登录复用双 token 迁移服务。兼容将来注册响应含 access token 时，注册页也先迁移再进 `/chat`。后端失败或本地写入失败都保留访客凭证与源历史，允许重新提交登录；服务端迁移成功、本地历史合并成功后才清 `guest_token`/`guest_status`。本地访客历史并入用户历史，按 `id` / `backendSessionId` 去重并保留当前会话、`pendingSession`、已答问题与上传轮询信息；不删除服务端 GuestSession。
- **本轮验证：** `frontend` 的 `npm test` **23 passed**；`npx tsc --noEmit -p tsconfig.app.json`、定向 ESLint、`npm run build`、`git diff --check` 均 exit 0。前端单测以内存 localStorage 和 HTTP 响应替身验证服务端 500 保留、用户本地存储写入失败后的幂等重试、合并去重与成功清理。Vite 有大 chunk 警告。
- **后端验证限制：** 曾尝试 `backend\.venv\Scripts\python.exe -m pytest tests\test_guest_migration.py tests\test_t3_document_persistence.py -q --tb=short -p no:cacheprovider`；T00 安全 fixture 在测试体前因缺少一致的专用 `TEST_DATABASE_URL`、`DATABASE_URL`、`ASYNC_DATABASE_URL` 拒绝运行，20 项均未执行，exit 1。未绕过数据库保护。
- **本轮真实接口探测与阻塞：** 新建合成访客并携有效访客 token 请求 `/agents/route/stream`，无论用 `guest_token` 查询参数还是 `X-Guest-Token` header 均返回 HTTP 500 `Internal Server Error`；浏览器显示“服务异常 / SSE connection failed”，因此无法产生可迁移的访客报告。脱敏机器记录 `.ai/tasks/patient-closure-evidence/patient-guest-migration-blocked-2026-09-27T22-33-03.196Z.json` 含 guest session ID、两种传递方式的状态/响应片段及浏览器页面日志；不含 token。未定位该服务端异常的根因；也没有安全可用的隔离测试库来运行迁移集成测试。T03 现标 `BLOCKED`，解除条件为修复/恢复访客问诊流，或提供经安全门禁认可的隔离 PostgreSQL 后运行现有迁移集成测试，再补注册→登录→迁移→病例/材料恢复证据。手动验收步骤见 `.claude/manual-test-guest-migration.md`。
- **独立复核与当前状态：** 第二轮 `gpt-6-sol / medium` 复核此前静态实现无 major；确认注册有 token/无 token 双路径、迁移失败保留重试条件和本地历史续接。新鲜独立复核确认 `BLOCKED` 比 `IMPLEMENTED_NOT_VERIFIED` 更准确，无 P0/P1；指出此前失败没有机器 artifact，本轮已增加以上脱敏证据。状态维持 `BLOCKED`，不标记 PASS。
- **本轮根因修复（2026-09-28）：** 定向回归复现访客 SSE 500 的代码根因：`route_stream` 的访客自动创建分支内再次导入模块顶层已导入的 `GuestSession`，使该名称成为函数局部变量；已有访客跳过创建分支后，在 `db.get(GuestSession, ...)` 触发 `UnboundLocalError`。移除局部导入后，query/header 两条依赖解析路径在 fake DB 单测中都能进入 SSE；仅在本次新建访客时发送 `guest_token`，前端接收并保存非空 token，不覆盖已有凭证。独立复核又发现失效访客及用户 token 会被 lenient 依赖静默变成匿名；现在仅无凭证请求返回匿名 context，显式 token 无效/过期返回 401，DB 解析异常继续抛出而不伪装成凭证错误；guest/access JWT 缺少或含非 UUID subject 也会被拒绝。新增正向 active-user claim 和多凭证优先级回归，统一无效凭证错误 detail。`backend/tests/test_guest_sse_token_event.py` 21 项通过；前端 `npm.cmd test` 28 项通过；`npm.cmd exec -- tsc --noEmit -p tsconfig.app.json` exit 0。后端测试运行于清空继承环境、无 `.env` 的工作目录，数据库 URL 指向未监听的本机端口，token resolver 与数据库均为替身，没有访问真实数据库。
- **当前状态仍为 `BLOCKED`：** 上述仅证明代码路径与前端事件处理，不代表真实 API 已恢复，也未验证 PostgreSQL 迁移、重复迁移、材料归属/恢复或真实凭证过期/他人隔离。需先有经安全门禁认可的隔离 PostgreSQL，再复测 query/header 真实 SSE，并完成注册→登录→迁移→病例/材料恢复与失败重试验收；此前 500 记录仍是最近的真实 API 证据。既有 Redis 黑名单查询在 Redis 异常时仍 fail-open，本轮未修改该策略。

- **2026-09-28 隔离浏览器/API 部分验收（非 PASS）：** `.ai/tasks/patient-closure-evidence/patient-guest-migration-20260928T045401Z.json` 记录合成访客 SSE 问题、材料上传、注册/登录、访客迁移 `migrated=1`、新患者病例恢复与材料下载、重复迁移 `migrated=0`、病例/材料无重复及前端访客 token 清理；病例 owner 与登录患者一致，页面错误为 0。运行前专用 `medaxis_test_closure_3ce15962` 有 0 张 public 表；API readiness 的 PostgreSQL/Redis 均为 ok；运行使用非超级用户，迁移 head 为 `b2c3d4e5f6a7`；清理后仍为 0 张表且临时角色已删除。LLM 使用确定性替身，文件解析队列发布使用替身（T07 worker/解析不在本任务）。
- **本轮缺口与状态：** 浏览器/API 主链路有真实隔离 PostgreSQL 支撑，但后置 SQL 所有权断言未执行：一次性验收驱动误把不透明的前端 `session_id` 当 UUID，停止在 `browser_api_sql` 阶段。该 artifact 只能证明浏览器/API 结果与库清理，不能代替 SQL owner/source 关联证据。独立只读身份复核也建议维持 `BLOCKED`：还需真实 API 的过期/他人访客凭证拒绝及迁移 500→重试证据；现有相关后端测试此前被数据库安全 fixture 拒绝、未执行。后续按最小切片补证，不重跑已通过的 UI/API 步骤。此前 `CELERY_BROKER_URL=127.0.0.1:59998` 会令上传发布等待超时，验收环境已明确替代解析任务发布；不据此推断产品上传故障。
- **T03 隔离 API/PostgreSQL 定向验收（2026-09-28）：** `backend/tests/test_guest_migration.py` 在唯一隔离库 `medaxis_test_closure_3ce15962` 最终 **9 passed、exit 0**；覆盖迁移归属、数据库过期访客拒绝、过期 JWT、缺失/非法双身份、重复迁移幂等、冲突患者所有权、注入提交失败后无变更并用同一身份重试成功，以及 PostgreSQL 并发迁移仅转给一个患者。最终机器证据 `.ai/tasks/patient-closure-evidence/t03-migration-api-db-20260928T052808Z.json` 记录初始 0 张表、非超级用户临时角色、清理后 0 张表且角色不存在。此前的浏览器/API happy path artifact 仍是另一轮证据。**当前状态：`PARTIALLY_VERIFIED`**；完整 G-A 仍需在同一新运行中对病例、source session、文件材料做直接 SQL 关联，不把分轮证据拼成同轮验收。

### T04 — 配额从显示值变成真实门禁

- **现状/位置：** `agents.py:854–874`、`auth.py:401–436,507–562`、`services/config.py:112`、`admin.py:92`。
- **实施：** 配置键唯一真源，两种访客创建路径一致；定义首轮、续答、报告后追问、失败重试哪些扣次，服务端原子校验与扣减；不把上传次数擅自当对话次数。旧访客配置变更是否追溯需记录。
- **验收：** 将允许次数设为 2，按冻结规则发请求：前两次允许，第三次明确拒绝；两个并发请求争抢最后一次只允许一个；失败重试不重复计费（若选择计费则需在契约先明确）；remaining 与实际一致，切换 SSE/非流式路径不能绕过，过期访客不可继续。配置键变更须给迁移/兼容说明。
- **A2 实现调查（2026-09-28，含独立核验）：** `/auth/guest` 读取 `guest.max_messages`（默认 999），管理端种子键为 `auth.guest_max_messages`（默认 10）；SSE 自动建访客仍硬编码 999。`GuestSession.message_count` 只有创建/返回/status 读取，服务端没有递增、原子门禁或请求幂等。除流式首问、补问和诊后追问外，`CurrentUserContext` 也接受有效访客 JWT，可调用非流式 `/agents/route`、`/diagnose`、`/plan`、`/monitor`、`/consult`；这些接口同样没有额度门禁。访客 token resolver 不查询 DB GuestSession 存在/过期，而 SSE 首问及续答/诊后追问路径有额外 DB 校验。实施前须裁决计费范围、失败扣次/返还和同一提交重试规则；建议覆盖全部访客可调用的模型入口，避免旁路。
- **用户裁决（2026-09-28）：** 配额覆盖全部访客可调用模型入口；服务端/模型失败返还额度；同一提交重试幂等。助手输出、助手发起的补问、文件解析上传不作为额外患者提交计次。
- **T04 当前缺陷复现（2026-09-28）：** 在隔离 PostgreSQL 的实际 `POST /api/v1/agents/route` API 上，分别使用数据库无记录和已过期 `GuestSession` 对应但 JWT 尚有效的访客 token，两个请求都返回 **200**；目标应为 401。红灯证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T062219Z.json`。该发现将共享身份有效期校验并入 T04 实施范围。
- **实施结果（2026-09-28）：** 统一读取管理配置 `auth.guest_max_messages`（默认 10）；5 个 REST 模型入口与首问/续答/诊后追问 3 个 SSE 入口均要求访客请求携带 `Idempotency-Key`，通过访客行锁原子扣次，并缓存同键终态。服务端/模型失败在终态发回前返还一次；超 15 分钟的 pending 在该访客下一次模型提交时回收额度，退款落库失败会向调用方冒泡。续答仅接受 POST，答案走 JSON body；三条患者 SSE 路由拒绝 URL 凭证和患者文本字段。计数单位是每次患者模型提交。
- **隔离 PostgreSQL 验收：** 命令 `& '.\backend\.venv\Scripts\python.exe' '.ai\tasks\2026-09-28-patient-closure-execution\run_t03_migration_tests.py' --test-file test_guest_model_quota.py --test-file test_access_control_integration.py --test-file test_guest_sse_token_event.py`，exit 0，**50 passed、48 warnings**。证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T091530Z.json`；目标 `medaxis_test_closure_3ce15962` 运行前 0 张 public 表，清理后 0 张，临时角色已删除。随后针对取消时退款落库错误的增补测试，配额文件 **16 passed、13 warnings、exit 0**；证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T093112Z.json`。
- **前端验收：** `frontend` 的 `npm.cmd test` 为 **31 passed、exit 0**；`npm.cmd exec -- tsc --noEmit -p tsconfig.app.json` exit 0。首问与续答测试确认患者文本在请求体、凭证和幂等键在请求头，传输级重试复用同一键。
- **独立复核与残余风险：** 独立只读复核确认 8 个模型入口、访客行锁、旧 pending 回收、终态先落库及 URL 敏感字段拒绝路径。幂等响应缓存含模型输出/患者上下文，随访客会话删除时级联清除；会话到期由 hourly Celery 清理，但本轮没有证明 beat 实际运行。全局身份解析器仍兼容其他路由的 URL token；三条患者 SSE 路由改用严格依赖，在调用通用身份解析器前拒绝 URL 凭证和患者文本。上游 HTTP access log 仍可能记录恶意/旧客户端发来的原始 URL；前端不会在 URL 中发送这些内容。T04 判定 PASS 不代表真实模型质量或清理调度运行态已验证。定向修复证据见 `.ai/tasks/2026-09-28-patient-closure-execution/logs/009-A2-T04-preauth-query-rejection.md`。

### T05 — 健康档案不再假保存

- **现状/位置：** `HealthProfilePage.tsx:76–89,211–243`，`patient.py:101–177`。邮箱/出生日期可编辑但更新 schema 不收；失败静默退出编辑。
- **实施：** 先让不支持字段只读并说明；如确需可编辑，单独确定邮箱变更与生日/年龄契约，补存储与校验。保存失败保留草稿/编辑态。现有过敏、慢病、用药、身高体重往返一致；不要默认为用户自动生成提醒。
- **验收：** 每个可编辑字段修改→保存→新请求读取→重登一致；422/500/断网保留草稿并显示失败；取消还原；未支持字段无法输入后丢失。档案变动影响摘要时按 T09 标识来源变更。
- **实施结果：** 前端 PATCH body 显式 allowlist 后端支持的姓名、手机、性别、身高、体重、过敏、慢病和用药字段；邮箱、出生日期只读并说明限制。保存失败保留编辑态与草稿，取消恢复最近已保存档案。身高/体重输入被清空时不转成 `0`，并提示当前接口不支持清空已有数值。
- **本轮验证：** `frontend` 的 `npm test` **25 passed**、`npx tsc --noEmit -p tsconfig.app.json`、定向 ESLint、`npm run build` 和 `git diff --check` 均 exit 0。构建有现存的大 chunk 警告。
- **本轮真实浏览器/API验收：** 在当前合成隔离 API/PostgreSQL 服务注册患者，浏览器修改姓名、手机、性别、身高、体重、过敏、慢病和药物并保存；新 API GET 逐字段对账，清浏览器存储重登后 API 与页面都恢复同值。自然非法身高返回后端 HTTP 422，输入草稿保留且数据库旧值不变。浏览器再拦截 PATCH 注入 HTTP 500、HTTP 422 与断网，页面均保留草稿/编辑态；取消恢复最后成功值。证据 `.ai/tasks/patient-closure-evidence/patient-profile-2026-09-27T22-33-55.699Z.json`；人工制造后端 500 的一轮试验在等待 PATCH 响应时超时，没有被计作通过证据。
- **独立复核与当前状态：** 最新 `gpt-6-sol / medium` 独立复核检查了 artifact、脚本和真实实现，未发现 P0/P1；确认注入 HTTP 500 满足 UI failure criterion（不等于服务端自然 500 测试），全部可编辑字段已往返并于重登恢复，T05 标记 `PASS`。自然非法身高返回后端 422。自然制造数据库 500 的尝试超时，未被计为证据；未知 PATCH 字段仍静默忽略，未做原始 SQL 对账，作为后续 P2 契约/证据项保留。手动验收见 `.claude/manual-test-patient-profile.md`。

### T06 — 真实模型主线与失败体验

- **现状/位置：** `backend/app/services/llm.py:142–191,214–265`，`api/v1/agents.py:1241–1270`；[冒烟题集](../../evals/patient-smoke/README.md) 为 DEFINED_NOT_RUN。配置异常原文会进入 SSE；是否当前有 provider 本次未查。
- **实施：** 在隔离合成环境确认可用 provider/平台匹配；执行 SM-01–SM-10 各自支持的模式，不能把 engineering 结果填到 live_model。配置缺失、上游超时/429/无效结构、取消、中断分别映射稳定错误码和患者可理解提示，原始细节留脱敏日志。
- **验收：** 全新患者用真实模型完成至少一次补问、报告、唯一病例、准备、反馈、重登恢复；留 provider/model/日期和每阶段耗时。无模型/失效配置/超时等失败不伪造报告、不泄漏密钥/内部配置，不引导患者操作管理员页面；可恢复输入并重试。首轮和续答均覆盖，报告后追问不得覆盖父报告。SM-02–04 另按 T09 核对。
- **判定：** 所有适用工程断言通过才 PASS；依赖不可用记 BLOCKED，不用替身顶替。成本、耗时先真实记账，未预先冻结 SLA 不造“达标”分数。
- **已实施：** 新增 `backend/app/services/llm_errors.py`，把显式配置错误、429、超时、provider、无效结构和内部错误映射为稳定 code 与患者提示，不向 SSE 发送 provider 异常原文；首轮、续答、诊后对话的模型错误路径使用此映射。病例保存失败、session 创建失败和诊后空回复也返回稳定错误码。请求取消继续向上传播并记中断 code，诊后对话 child 标为失败；日志仅记录阶段、错误码和异常类型。Structured Output 仅在 provider 明确拒绝 `response_format/json_schema` 时 fallback，超时和其他上游失败不会重复请求。
- **本轮验证：** 最新受控子进程运行 `python -m pytest tests/test_patient_llm_errors.py tests/test_intent_latency.py -q --tb=short -p no:cacheprovider`：**35 passed，exit 0**；工作目录位于任务隔离目录、未读取 `.env`，数据库 URL 指向无服务的本地测试端口，测试只使用合成依赖。更早一轮为 31 passed。`git diff --check` exit 0（仅有仓库文件的 LF/CRLF 提示）；`python evals/patient-smoke/run_eval.py --check` 历史结果 exit 0，输出 `status=DEFINED_NOT_RUN cases=10 split=dev_smoke`。评测集校验不调用模型，也不是模型主线证据。
- **早期独立验收复核：** 首轮 `gpt-6-sol / medium` 复核指出诊后空回复缺稳定 code、病例保存错误继续透传异常以及 `ValueError` 分类过宽，本轮已补 `LLM_EMPTY_RESPONSE`、`CASE_PERSISTENCE_FAILED` 和显式 `LLMConfigurationError`，并补空回复/取消状态回归。第二轮独立复核指出病例保存失败分支缺少逐分支断言。本轮为三个可达保存失败路径补了合成断言：首轮结构化报告、续问已完成报告、续问新生成报告。另补 session 创建失败回归：原流程会继续生成未关联病例的报告；现在以 `DIAGNOSIS_SESSION_CREATION_FAILED` 结束且不发结构化报告或完成事件。原 `route_stream` analyze 回退及其重复保存 catch 已删除，避免 session 创建失败时回退为无病例报告。状态仍为 `BLOCKED`：真实 provider、隔离 PostgreSQL 和浏览器主线未运行，后续必须按 `.claude/manual-test-t06.md` 验收，不能用替身代替。
- **历史状态（截至 2026-09-28）：** `BLOCKED`。当时尚无获准的隔离 PostgreSQL/provider 运行条件；不得用工程替身或 `DEFINED_NOT_RUN` 标记 PASS。
- **2026-09-29 隔离真实模型验收：** 用户批准在现有 PostgreSQL 容器中创建并清理一次性 `medaxis_test_t06_*` 库，复用现有 Admin DeepSeek `deepseek-flash` 配置（密钥仅在内存中重加密），不创建容器、不外发管理员知识库文档。合成患者真实问诊→补问→结构化报告→唯一病例→准备/反馈→浏览器清缓存重登恢复，同轮 API/SQL/浏览器证据通过；合成内部知识条目检索后在报告以 `[S1]` 标注文档和片段。SM-02 过敏史未知、SM-03 起病时间未知、SM-04 体温前后矛盾的真实模型内容已核对；SM-03 曾错误写“慢性咳嗽”，经 prompt 与保存前确定性约束修复后定向真实模型复验通过。题集映射工程测试 **25 passed、exit 0**；模型错误/取消定向测试 **41 passed、exit 0**；前端引用规则 **2 passed、exit 0**。原始证据、耗时与成本缺失值见 `evals/patient-smoke/results/2026-09-29-t06-deepseek-live.json` 及 `.ai/tasks/2026-09-28-patient-closure-execution/logs/016-A3-T06-isolated-live-acceptance.md`。
- **2026-09-29 外部来源同轮复验：** 用户重启现有 `medaxis-backend` 后，在原隔离方案中通过仅绑定 `127.0.0.1` 的临时转发访问现有 SearXNG。首轮发现测试库超时误设为 1 秒，问诊虽完成但报告只有内部引用；将本次隔离测试超时调为 30 秒后复验通过：真实 DeepSeek 问诊 10 次补答、检索 10 条，报告含 1 条合成内部来源和 5 条外部来源，其中 3 条 HTTPS。临时数据库、角色、Redis DB14 和转发服务均清理。证据 `.ai/tasks/patient-closure-evidence/t06-live-api-20260929T095723Z-c92e03666cfe.json`。这证明最终报告能带外部链接，但来源的医学相关性/权威性未逐条人工审查。
- **可信来源筛选修复与复验：** 真实模型报告暴露患者问诊工具没有执行 Admin 的 `external_search.trusted_only=true`。现已在工具入口按既有设置过滤指南与普通搜索结果，配置为 false 时保留所有结果。先失败后通过的回归 `tests/test_knowledge_citations.py` **13 passed，exit 0**。修复后的同轮真实报告含 `[S1]` 合成内部来源及 `[S4]` 外部来源“关于印发诺如病毒胃肠炎诊疗方案（2025年版）的通知”，链接为 `http://www.natcm.gov.cn/...`，`is_trusted=true`；一条合法 HTTP 链接也满足当前安全 URL schema。证据 `.ai/tasks/patient-closure-evidence/t06-live-api-20260929T101510Z-5f8c5e3895dc.json`。页面目标访问检查超时，未验证其内容与报告的逐条医学对应关系。
- **最新状态：** T06 核心主线、合成内部引用、可信外部来源筛选及同轮外部 URL 引用均有真实模型/API 证据，T06 **总体仍为部分完成**。当前授权不包含将管理员已上传的私有文档片段发送给外部模型，因此实际私有文档在最终报告的引用仍未验证。SM-04 仅在主诉和报告保留两句，准备包未另建 `unresolved` 事实，归 T09。用户在可信域名筛选代码修改前重启过 `medaxis-backend`；修改后使用隔离 API 验证，运行中的 `:8000` 容器还需重新启动才会加载该修复。

### T07 — 真实文件从上传到原病例

- **现状/位置：** `api/v1/documents.py:74–152,216–289`、`tasks/documents.py:66–109`、`api/v1/agents.py:760–826`、`ChatPage.tsx:658–724`。数据库任务与 worker 已有实现，不应重写成另一套文件服务。
- **实施：** 用标明合成的图片及 PDF/文本跑真实解析提供方，验证其实际支持的文件协议（不能由“OpenAI 兼容 chat”推断文件接口兼容）。补必要的 UI/关联修复及失败恢复。
- **验收：** 合法图片和文档完成上传→解析→原会话→原病例；内容可对照原文。超 10MB、非法格式、损坏文件、提供方失败、队列不可用均有终态或明确可恢复状态。上传刚返回 ID 时刷新、切换会话、暂停/恢复 worker、重启 API 后仍归属正确；跨患者读写/删除拒绝；失败不当正常检验值。返回错误须脱敏。
- **解析器局部修复：** TXT 解码优先 `utf-8-sig`，避免 UTF-8 BOM 的 `U+FEFF` 成为正文；合成单测覆盖普通 UTF-8、UTF-8 BOM、GBK 和 latin-1 最终回退。自动编码探测中 GBK 与 latin-1 存在字节歧义，真实文件协议仍须用标记为合成的样本验收。单测不证明真实 provider、上传任务或 worker 闭环。
- **已实施：** 病例恢复 API 的 `lab_reports` 在前端明确为 `LabReportResult[]`；病例详情按 `file_id` 将解析结果放在该材料的渐进展开区，并复用聊天页的 `LabReportCard`，显示指标、参考范围、异常方向、置信度和人工复核状态。完成任务但缺结果时给出提示；材料处于 queued/processing 时每 1.5 秒刷新病例恢复，最多 80 次后提供手动刷新。
- **本轮验证：** `frontend` 的 `npm test` **26 passed**；`npx tsc --noEmit -p tsconfig.app.json`、定向 ESLint、`npm run build` 均 exit 0；Vite 提示既有的大 chunk 警告。
- **早期独立验收复核：** 首轮 `gpt-6-sol / medium` 复核指出病例恢复页缺处理中材料轮询，本轮已补有界轮询和手动刷新入口，新增轮询状态判定测试；第二轮指出临时轮询失败时旧详情与错误提示冲突，本轮改为保留旧详情、显示状态更新提示并继续有界重试。当时仍为 `BLOCKED`：后端已有上传任务持久化、worker 重投标记、会话/病例关联和 owner 隔离测试；前端已有合成 mock 浏览器流程，但未运行真实解析 provider、隔离 PostgreSQL、broker/worker 重启或本页真实浏览器交互。不能把 mock 流程当真实解析通过。
- **本轮追加验证：** 新增 `backend/tests/test_document_parser.py` 的四条解码用例。BOM 用例 TDD 先失败（解析结果以 `U+FEFF` 开头）再通过；解析器文件 **4 passed**。与此前八个安全回归文件合并，在清洁子进程、任务隔离工作目录、无 `.env`、死端口 DB URL、禁用 pytest cache 下共 **115 passed**（2 条仅测试 JWT 短密钥警告）。独立 `gpt-6-sol / medium` 局部复核首轮指出缺少普通 UTF-8/GBK/latin-1 覆盖，已补齐；第二轮未发现 P1/P2。该证据只验证合成单元路径；T07 仍为 `BLOCKED`，真实文件解析、provider、隔离 PostgreSQL、broker/worker 重启及真实页面时序尚未验收。

### T08 — 把持久化和隔离证明补齐

- **复用：** `backend/app/services/patient_case_persistence.py`，`test_patient_demo_case_closure.py`，`test_t3_document_persistence.py`，已有病例/准备/反馈 UI 防串号测试。
- **实施/验收：** 同来源会话顺序和并发完成分别验证病例数量恒为 1；真实 Redis 锁，不用演示 server 的锁替身。注入病例保存失败时不能显示已保存；已生成内容可读/可重试。清缓存、换浏览器、重启隔离 API/worker 后恢复相同 `case_id/source_session_id`、准备修订和反馈修订；A→B 失败/迟到响应不串号。
- **权限矩阵：** 患者 A/B、访客、过期身份、未认证/授权/非授权医生分别访问病例、来源报告、材料、准备、反馈、计划与确认。拒绝用例全部不得泄漏正文/修改记录；状态码按已有 401/403/404 契约固定，不能只看页面隐藏。检查通用病例创建/修改的来源会话归属，不能只测患者专用 recovery。
- **已实施：** 通用病例创建仅允许患者角色；指定 `source_session_id` 时，必须找到且属于当前患者，否则用通用 404 拒绝，避免泄漏会话存在性。新增四个路由函数回归测试覆盖合法患者创建、跨患者来源、不存在会话及医生创建。
- **本轮验证：** 从仓库根目录执行 `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/test_patient_case_ownership.py -q --tb=short -p no:cacheprovider`，**4 passed**。尝试用内存 SQLite 配置整套 fixture 时，应用配置拒绝 SQLite 的 `DATABASE_URL` scheme；不绕过安全门禁、不连接任何数据库。
- **早期证据与缺口（已由下方隔离验收更新）：** 代码中已有同源病例顺序幂等和提交失败回滚测试，但本轮隔离数据库门禁未允许运行；worker 重复解析并发测试仅 PostgreSQL 执行，Redis 锁在演示服务中由 `_LocalDemoLock` 替代。准备包有 CAS/顺序幂等测试，反馈有顺序幂等测试。仍未获得 PostgreSQL 行锁、真实 Redis 锁、API/worker 重启恢复、全权限矩阵和 A→B 浏览器迟到响应的本轮证据。
- **早期独立验收复核：** 独立 `gpt-6-sol / medium` 复核未发现 P1；提醒补充合法患者创建、不存在会话及来源查询条件断言，本轮已补。当时仍为 `BLOCKED`：这些路由函数测试使用 fake session，虽断言查询实体和目标会话 ID，但不执行真实 SQL/HTTP 序列化；本轮没有按 `tests/database_safety.py` 配置的隔离 PostgreSQL，也未配置可确认隔离的 Redis、API/worker 和浏览器运行环境。不得把替身锁、顺序测试或静态 owner filter 当作真实并发及端到端通过。手动步骤见 `.claude/manual-test-t08.md`。
- **隔离 PostgreSQL 定向验收（2026-09-28）：** `test_patient_demo_case_closure.py` **4 passed**，覆盖顺序幂等、同一 `source_session_id` 两个数据库事务并发保存时病例 ID 相同且仅一行、跨患者来源拒绝及保存失败回滚；`test_t3_document_persistence.py` 中病例本地缓存丢失恢复与材料下载 owner 检查 **2 passed**。机器证据分别见 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T053717Z.json`、`patient-api-db-20260928T053333Z.json`；两个运行均初始 0 表、最终 0 表且临时角色已删除。并发用例验证 PostgreSQL 来源行锁，不证明 Redis 锁争用或完整浏览器/重启链路。另有 T00 同轮 artifact `.ai/tasks/patient-closure-evidence/t00-testdb-e2e-20260928T033515Z.json` 证明真实 Redis 对同一 source session 执行 `SET NX EX 60`，并与浏览器/API/SQL 对账；其报告为确定性替身。**当前状态：`PARTIALLY_VERIFIED`**；live-model 最终 G-A 仍需同轮保留 Redis 锁证据并验证 API 重启及跨浏览器恢复。

## T08 后续隔离权限验收（2026-09-28）

- `test_access_control_integration.py` **3 passed，exit 0**；覆盖授权/未授权医生、患者不得访问医生路由、公开注册不能提权为 admin，以及病例解析结果和附件在患者/访客身份间隔离。
- 机器证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T054922Z.json` 记录专用隔离库初始 0 张表，清理后 0 张表且临时角色不存在。
- `test_t3_document_persistence.py` 中补问续接 owner、诊后追问 owner 与过期访客材料拒绝三项 `-k` 定向用例 **3 passed，8 deselected，exit 0**；证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T055523Z.json` 同样记录隔离库清理归零。准备/反馈 API 的患者 B、医生拒绝及材料归属拒绝已在上一轮 7 项 PostgreSQL API 测试中覆盖。
- T08 分轮 PostgreSQL/API 并发、恢复及权限相关用例累计 **12 passed**。配额扣减、访客对病例/准备/反馈端点的完整拒绝表、重启与迟到响应仍需最终契约/组合验收。
- 因此上方较早的“当前仍为 BLOCKED / 尚未运行隔离库”状态已过时。当前 T08 为 `IMPLEMENTED_NOT_VERIFIED`：完整患者/访客/过期身份权限矩阵、API 重启与跨浏览器恢复、A→B 迟到响应及真实模型同轮 G-A 仍未完成。

### T09 — 摘要来源语义与诊后反馈

- **现状/位置：** 原逻辑只用字段是否为空识别缺失，会把 `pmh_allergy='不清楚'` 作为普通已知事实。`InterviewState.raw_answers` 只留最近一次回答，摘要因此无法可靠识别先后矛盾。
- **实施：** 明确区分没问、回答不清楚、明确否认、明确肯定和互相矛盾；保留原话与来源，必要时补状态而不是简单关键词猜测。复用现有版本、冲突与自报逻辑。
- **验收：** SM-02–04 覆盖“不清楚/明确否认/前后冲突”，不把未知变否认、不造日期、不静默选一边。准备页面和复制文本状态一致；来源变动后旧摘要标待核对；两标签页旧 revision 保存 409，不覆盖新值；准备/反馈 500 保草稿、不新增成功修订；反馈始终标患者自报，不自动变为医生意见或用药任务。
- **实施结果：** 新增 `backend/app/models/patient_answer.py` 的确定性未知/否认/肯定识别，覆盖精确标记及受控的不确定短语（如“我不记得哪天开始”）；问诊状态向后兼容地保留每个问题的有序原始回答，未知原话和多次不一致回答不会被摘要成最新单一事实。准备包记录回答原文、来源、明确否认/肯定状态及 `unresolved_facts`，把来源回答纳入指纹；患者页面和复制预览均展示未知原话、明确状态标签与全部矛盾陈述，并允许患者补充而不覆盖原始回答。诊断提示明确禁止推断日期、忽略矛盾或把患者自述写成医生确认。`SM-02–04` 映射到确定性工程测试，目录仍为 `DEFINED_NOT_RUN`。
- **本轮验证（2026-09-28）：** 在不读取 `.env`、数据库 URL 指向未监听回环端口的隔离子进程运行 `backend/tests/test_case_preparation_semantics.py`：**15 passed，exit 0**。`frontend` 的 `npm.cmd test`：**28 passed，exit 0**；`npm.cmd exec -- tsc --noEmit -p tsconfig.app.json` exit 0；`npm.cmd run build` exit 0（Vite 提示 655 kB chunk 与 plugin timing）。`evals/patient-smoke/run_eval.py --check` exit 0，10 案例 `DEFINED_NOT_RUN`、`CATALOG OK (defined, not run)`。这些检查不连接真实 API/数据库/provider。全仓 `npm run lint` 历史上 exit 1（37 errors / 3 warnings，其他文件）；不能声称全仓 lint 通过。
- **独立复核：** 首轮 `gpt-6-sol / medium` 指出自然语言未知长句未进入 unknown，以及准备页未显示与复制文本一致的状态标签；已补充贯穿问诊状态到准备包的无数据库回归，并统一页面/预览标签和未知原话显示。第二轮独立复核未发现有证据的 P1/P2。
- **本轮 UI-only 浏览器回归（2026-09-28）：** `patient-t09-ui-mock-1790553068906.json` 状态为 `PASS_UI_ONLY`。真实患者页由 Playwright/Edge 加载，浏览器内存 mock 覆盖 33 个 API 请求；验证 stale 摘要禁止复制、准备页 500 保留草稿、标签页 A 将 revision 1 保存为 2 后标签页 B 的旧 revision 收到 409 且保留草稿、诊后反馈 500 保留输入后重试成功并标记 `patient_reported`。0 个未预期 API 请求、0 个页面异常；`databaseTouched=false`、`realModelUsed=false`。这是前端交互证据，不证明真实 API/CAS/数据库持久化、来源变化后的 stale 计算或重启恢复。
- **未覆盖与当前状态：** `IMPLEMENTED_NOT_VERIFIED`。仍未在隔离 PostgreSQL/API 上验证修订冲突、来源变更、重启恢复及服务端 500 不产生成功修订；未运行真实模型 `live_model` 或医学内容人工复核。当前 `is_unknown_answer` 按子串匹配受控不确定短语；例如“青霉素过敏，但我不知道具体症状”会把整个过敏字段归为 unknown，虽然原话仍会保留，尚不能表达“事实明确、细节未知”的范围差异。新增场景须先由产品/临床复核者冻结语义：保留患者原话及来源，不得静默丢掉明确陈述、不得把自述升为医生确认、不得臆造未知细节。确定性规则不能代替医学判断；手动步骤见 `.claude/manual-test-t09.md`。
- **隔离 PostgreSQL API 定向验收（2026-09-28）：** `test_case_preparation.py` 与 `test_case_post_visit_feedback.py` 合计 **7 passed**；覆盖来源快照/来源变化、准备包版本与旧 revision 409、保存失败不生成新版本、患者自报标记与 owner 检查。机器证据 `.ai/tasks/patient-closure-evidence/patient-api-db-20260928T053306Z.json` 记录专用测试库初始 0 表，测试后 0 表且临时角色已删除。**当前状态：`PARTIALLY_VERIFIED`**；仍需真实模型报告来源变化后的 G-A、重启恢复和医学人工审核。

### T10 — 医生意见进入患者病例（C 前置）

- **现状/位置：** `doctor.py:29` 只查角色；通用 `medical_cases.py` 的医生更新分支也须检查认证。病例分配仅 admin；通用详情已有医生字段，患者 `patient.py:201–267` 与页面未接上。医生详情含演示数据的路径须一并处理。
- **实施：** 按 D1 打通真实授权/分配→已认证医生确认/修正→患者展示；复用现有 diagnosis PATCH。AI 报告和医生意见分开，展示作者、时间、状态、意见版本；不要求先造 DoctorAgent。移除本链路的 mock 成功回退。
- **验收：** 已认证且授权医生保存后患者重开可读；患者 A 不读 B；未认证/未授权医生经所有旁路均不能读取/修改；保存失败保留草稿。患者自报不改变医生确认状态；再次修订有可识别版本。D1 未定可验证现有 admin 分配，但不得声称患者自助送审已完成。

### T11 — 计划生成与生效

- **现状/位置：** `services/agents.py:969–1032` 的 `generate_care_plan` 未发现生产调用方；`api/v1/agents.py:630` 仅返回 plan 生成结果；`doctor.py:214–235` 计划接口 501。随访页空态承诺“完成问诊后会出现事项”，当前没有此生产链。
- **实施：** 按 D2 建立触发、草稿、人工确认、生效、取消；任务数组有稳定唯一 ID、类型、时区、时间/频次、状态、来源病例及计划版本。生成使用结构化校验；计划与事件写入的失败可恢复且不重复。患者自报复查事项仅进入待核实草稿，不自动产生临床用药任务。
- **验收：** 从真实 API 发起（不手工插表）得到计划且患者可见；重复提交只产生约定的一份有效计划；无效模型 JSON 不留下“有效空计划”；未批准不发送；取消后停止未发送任务并保留既有执行历史；请求失败页面无成功提示。

### T12 — 随访打卡、数值反馈和进度

- **现状/位置：** `patient.py:835–867,936–968` 未知 task_id 仍返回 success；JSONB 嵌套原地修改可能不被脏检测，**这是待集成证伪风险**；check-in 只处理 dict。`FollowUpPage.tsx` 目前主要是完成复选框，没有数值/备注上报流程；计划 API 的 goals 为固定空数组。
- **实施：** 冻结单一任务契约；未知 ID 拒绝，归属检查、幂等更新与数据库可观测持久化；患者按任务填值/备注，完成进度与计划状态一致；取消/过期计划按明确规则处理。需要兼容旧格式时显式转换，不继续扩散双写。
- **验收：** ack/check-in 成功后新 DB session、刷新和重登仍有正确状态/value/notes；不存在任务 404 且数据库不变；跨患者拒绝；重复确认不增加执行次数；非法数值 422；取消任务不能被回执复活；进度与实际已完成任务一致。确认通知、服药自报、完成随访任务三者不混用。

### T13 — 提醒调度与可靠终态

- **现状/位置：** `agents.py:1019–1028` 只为 medication 固定 +1h；`tasks/monitoring.py:239–248,313` 发送失败回 pending，重试次数达到阈值后扫描不再选中，却未变 failed。
- **实施：** 按批准计划频次、开始/结束时间和时区生成任务；覆盖本次支持的 follow_up/self_check；幂等键、防重复投递、取消校验、超限 failed 终态和受控重试。不要承诺邮件外部服务 exactly-once。
- **验收：** 使用可控时钟与测试邮箱：给定固定频次/疗程，事件数、时间和任务 ID 与预期逐项一致；重复 worker 投递只产生一次有效业务状态转换；暂停后恢复补偿到期任务；发送异常最多约定次数后 failed 可见；进程在发送前/后崩溃分别记录结果和可能重复窗口；取消后不再发送。分别统计计划、应发、尝试、服务接受、失败、患者确认，差额均可解释。

### T14 — 异常反馈闭合到人

- **现状/位置：** `MonitoringAgent.check`（`services/agents.py:1055`）返回评估；`patient.py:936` check-in 没有调用监测与升级。`api/v1/__init__.py:14` 通知入口为 admin 范围；存在 health_alert 发送模板不等于已产生业务事件。
- **实施：** check-in→受审规则/人工可核实评估→持久异常事件→指定负责医生收件箱→回执与状态；患者看到已提交/待处理/已处理。新增接口是方案，不要把 `/notifications/me` 当既有 API。送达失败及无人接收需有真实状态。
- **验收：** 固定合成异常产生一个关联患者/病例/任务的事件，重复请求不重复升级；负责医生可见并回执，非授权医生不可见；重启后仍可追踪；无人接收/发送失败不显示“医生已获知”；患者可见处理结果。专业阈值与职责未确认时记 BLOCKED，不让模型编造规则。

### T15 — 个性化科室建议（条件扩展）

- **现状：** `PatientCasesPage.tsx:14–47` 中性演示目录；`services/case_preparation.py` 返回依据不足。已完成的是展示，不是推荐。
- **前置/实施：** D4 确认科室词表、审核来源、适用范围与审核责任人；给出推荐理由、来源定位、版本、缺失信息和降级。不要求预约/HIS。
- **验收：** 经审核的正例能给出可追溯建议，缺失/矛盾/无来源时不编造；原报告风险提示不被导航阻挡；来源变更标记待重评；专业审核记录独立于工程测试。缺前置继续保留“依据不足”，任务不得标 PASS。

### T16 — 云端聊天与健康画像（条件扩展）

- **现状：** `api/v1/agents.py:685–753` 会话列表/详情限 admin/doctor；患者聊天主要 localStorage。病例恢复已存在，不等于完整聊天同步。健康画像有后台生成路径但患者未形成可读、可刷新且来源清楚的展示。
- **实施：** D5 若纳入范围，提供仅本人会话列表/详情、分页与后续追问恢复；区分患者原始档案和 AI 汇总画像。定义本地删除/服务端删除及保留策略，禁止随手开放管理员会话接口给所有患者。
- **验收：** 新浏览器恢复历史与父报告关联，继续追问不覆盖父报告；超过一页可达；A/B 无互串；删除/过期按已选策略不重新冒出。画像显示来源、生成时间、过期/刷新失败状态，原始档案不被生成覆盖。

## 4. 仅阻断相关任务的前置决策

| ID | 执行前必须冻结 | 建议默认方向（不是已批准决策） |
|---|---|---|
| D1 | 病例给谁看、谁分配/认领、患者如何授权/撤回 | 先复用 admin 分配验证 C，再单独批准患者共享；不可开放任意认领 |
| D2 | 计划谁批准、何时生效、患者可取消什么 | AI 仅草稿；授权且已认证医生确认后生效；自报事项不自动用药 |
| D3 | 异常接收人、处理职责、超时及无人接收语义 | 持久事件+明确负责医生；不承诺全天候监护 |
| D4 | 个性化建议的审核词表、来源、适用范围 | 缺依据继续降级，不阻断 A |
| D5 | 完整云端聊天/画像是否本期必交及保留策略 | 后置；已保存病例恢复仍是 A 必交 |

邮箱验证、停用/删除策略、全量运营审计、供应商故障切换、SearXNG、MCP、GraphRAG 不作为本患者清单的顺手扩建项。发现它们阻断具体场景时记录依赖，再限定修复。预约/HIS 不在本计划。

## 5. 统一验收规程（给后续验收模型）

### 5.1 最终场景

| Gate | 操作与通过条件 | 关联任务 |
|---|---|---|
| G-A | 全新合成患者、真实模型至少一轮补问→报告→唯一病例→准备核对/复制→自报反馈；清缓存、新浏览器和服务重启后重读，对象与版本一致 | T00、T02、T03、T06、T08、T09 |
| G-A-FAIL | 无配置/超时/保存失败/旧版本/跨账号/反序响应无伪成功和串号；11+ 病例均可达；档案保存往返、访客配额与迁移通过 | T01–T06、T08、T09 |
| G-B | 图片和文档真实解析参与本次问诊；上传/worker/API 故障恢复与跨患者拒绝通过 | T07、T08 |
| G-C | 授权医生确认→患者读取→批准计划→到期提醒→确认/数值反馈→异常事件→负责医生回执；失败/重复/取消/重启逐项通过 | T10–T14 |
| G-D | 分别验收有依据科室建议、云端聊天/画像；未启用则 DEFERRED，不填 PASS | T15、T16 |

每个成功场景同时对照浏览器、接口响应和新事务数据库读取。页面截图或 API 200 单独不足。用合成账号/文件；不修改线上数据，不向真实患者发送通知。

### 5.2 证据与结果模板

建议每轮独立记录 `docs/product/CLOSURE_ACCEPTANCE_<日期>_<批次>.md`，原始日志放执行者指定的不含凭据目录。禁止覆盖旧成绩、修改题集降低标准、skip 失败用例后声称全通过。

```text
任务/验收 ID：Txx / G-xx
状态：PASS | FAIL | BLOCKED | NOT_RUN
代码基线：commit + dirty files / diff 或文件哈希
环境：OS/runtime、隔离 DB 名、实际 Alembic head、前后端地址
依赖：provider/model/版本；Redis/Celery/解析/邮件是否真实；替身完整清单
输入：合成账号编号、案例 ID、文件哈希、固定时间/时区
步骤：可复跑命令及操作（无密钥）
预期：对应本文可观察断言
实际：HTTP/事件、UI 状态、case/session/plan/task/event ID、版本与数据库对账
测试：命令、exit code、passed/failed/skipped；日志/截图路径
反例：错误、权限、并发、重复、退出/恢复结果
未覆盖项：明确原因；不以历史结果或替身结果代替
复核者：独立复跑结果和差异
```

PASS 必须附证据；IMPLEMENTED_NOT_VERIFIED 不计完成。依赖不可用记 BLOCKED。A/B/C 分开宣告，任何越权、串号、伪成功、重复有效记录或丢失已保存记录都阻断对应 Gate。安全/功能断言必须全通过；性能/临床质量另按预先冻结的口径，不能事后造阈值。

### 5.3 已有命令入口

```powershell
# 根目录：只校验题集，不运行模型/数据库
.\backend\.venv\Scripts\python.exe evals/patient-smoke/run_eval.py --check

# frontend 目录
npm.cmd test
.\node_modules\.bin\tsc.cmd -p tsconfig.app.json --noEmit
npm.cmd run build
```

后端 pytest、`run_eval.py --pytest` 必须先准备一份**专用、空的、可清空** PostgreSQL 测试库（库名以 `medaxis_test_` 开头），与演示库分离；设置 `TEST_DATABASE_URL`、`DATABASE_URL`、`ASYNC_DATABASE_URL` 为同一连接，另显式设置 `MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB=1`。测试 fixture 会在创建表及退出清表前校验这些值，并打印不含凭据的目标标识。缺项、目标不一致或库名不符都会在 DDL 前拒绝。当前容器数据库不可用时不得改连现有演示/业务库。本次未运行后端集成。浏览器脚本显式指定 URL/严格端口；API mock UI 回归与真实 E2E 分开标记。

## 6. 本轮审查证据与限制

- 本轮新增 T00 安全切片；之前 3 个只读探索覆盖患者界面、患者/随访后端、问诊/上传与测试。主审补查 T00 对象对账逻辑和拒绝路径。未改患者业务行为。
- `frontend`：`npm.cmd test` 输出 **12 passed / 0 failed**；同次命令组完成 exit 0；`tsc.cmd -p tsconfig.app.json --noEmit` 显式 `TSC_EXIT=0`。
- 根目录：`.\backend\.venv\Scripts\python.exe evals/patient-smoke/run_eval.py --check` exit 0，`CATALOG OK (defined, not run)`，10 个案例；首跑控制台中文编码不匹配，设置 `PYTHONIOENCODING=utf-8` 后复跑显示正常。该检查不执行案例。
- `frontend`：`npm.cmd run build` exit 0，11965 modules transformed，built in 15.13s；保留大于 500KB chunk 和插件耗时警告。
- 文档：Python 标准库检查 exit 0，`DOC OK: 14 links; 17 unique task sections; UTF-8 no BOM`；检查所有 Markdown 链接目标、行号上界、T00–T16 唯一连续编号、Gate/决策标识。`git diff --check` exit 0（仅覆盖已跟踪差异）；新增本文另查行尾空格和编码。Git 提示既有两份文档后续可能 LF→CRLF，不是业务测试错误。
- 没有运行后端集成、真实模型、浏览器 E2E、解析/邮件或服务重启；没有读取 `.env`、秘密或真实患者数据。新文档的验收是结构、证据与执行合同验收，不是应用闭环验收。
- 结论置信度：明确代码断链/参数/错误处理缺陷高；JSONB 丢失更新、上传恢复时序、实际运行依赖状态仍需集成验证，未写成已复现故障。

自审的主要失败风险：把合成演示当真实模型；遗漏通用 API 权限旁路；误用测试库导致清表；把缺乏业务入口当仅缺测试；执行模型擅自决定临床规则/扩大开发范围。本文分别用分层 Gate、权限矩阵、T00、任务类型和 D1–D5 限定。

## 7. 可直接交给执行模型的指令

> 阅读本文件和当前仓库规则，先复核代码基线及未提交改动。按 T00 起逐项执行，默认先完成 T01–T09 并提交 G-A/G-B 证据；保留现有已实现的病例、准备、反馈与解析持久化逻辑，不重建系统。每项先复现/补失败用例，再最小实现，最后按对应验收反例验证。只把带真实本轮证据的任务标 PASS。外部依赖或前置决策缺失时，将受影响项标 BLOCKED，继续独立任务；不得假造 provider、医生审核、送达、病例或报告。T10–T16 是独立后续范围，先确认本文对应决策与执行批次，再实施。交付任务状态表、变更文件、命令与退出码、对象对账、失败场景证据及未覆盖项，供另一模型独立复验。不操作生产、不永久删除、不覆盖用户现有改动。
