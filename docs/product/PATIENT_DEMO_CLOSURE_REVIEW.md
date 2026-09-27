# 患者侧闭环独立审查与验证说明

日期：2026-09-26。审查对象：当前源码及 `PATIENT_DEMO_CLOSURE_PLAN.md`。

结论：**患者侧合成展示主线已具备闭环实现；真实模型链路尚未验收。审查建议 REQUEST CHANGES，先修复复跑说明中的测试库复用问题。** 本轮未修改业务源码，也未重新执行整条真实认证/数据库的浏览器 E2E；原验收中的 92 passed 和新患者 E2E 属于上一轮记录。

## 已接通的范围

注册患者问诊完成后，首轮/续答的流式分支调用统一病例保存服务；按来源会话锁定并复用病例，失败返回错误，完成事件携带 `case_id`。报告入口使用该 ID 打开病例页；病例恢复校验 ID，切换失败不显示另一病例；已有风险信号在准备内容之前展示。准备核对、摘要预览/复制和患者自报反馈均有服务端 API、版本控制及归属校验。

科室导航目前是中性演示名称目录，点击只改变本页浏览选择，不会生成个性化推荐、记录预约或对接真实医院。诊后反馈是患者自述。上述能力可用于患者侧原型展示，不能写成医生诊疗闭环。

## 审查发现

1. **P1：复跑回归会清除演示业务表。** 原本地复跑说明把 `TEST_DATABASE_URL` 指向刚完成 E2E 的演示数据库。`backend/tests/conftest.py:39` 在会话级 fixture 结束时执行 `Base.metadata.drop_all`。照做会删除该库的用户、会话、病例、准备和反馈等 ORM 表，演示记录无法继续使用；Alembic 版本表可能仍在，单纯再次 upgrade head 未必会重建这些表。修复：回归使用另一个全新的一次性测试库，所有测试 DB 环境变量指向该库；演示库单独保留。不要用测试命令连接 `medaxis`。
2. **P2：浏览器回归默认端口与说明不一致。** runbook 启动前端 3002，但 `frontend/tests/chat_history_browser.py:14` 默认访问 3001。应显式设置 `CHAT_TEST_URL=http://127.0.0.1:3002` 后运行，启动 Vite 加 `--strictPort`，避免误测另一个页面。
3. **P2：验收证据需收紧表述。** `backend/tests/patient_demo_server.py:105-115` 同时替换 Redis 锁，不能称为只替换模型，也不能据此判断并发互斥正确。`backend/tests/patient_demo_e2e.py:155` 把迁移 head 写成固定字符串，未查询真实版本；脚本也未直接验证来源会话与病例的数据库关系。应读取实际版本和来源关系再写证据，并明确 Redis 替身边界。上一轮报告中的人工数据库核对记录与脚本自动断言须分别陈述。

运行环境阻断：本轮查询 `medaxis` 得到迁移版本 `b2c3d4e5f6a7`，模型配置总数/激活 diagnosis 配置数为 `0/0`。这解释了当前不能开始真实问诊；合成演示替身可以绕过外部模型依赖，但不能证明该问题已解决。

## 本轮新执行的检查

| 检查 | 命令或方法 | 结果 |
|---|---|---|
| 后端定向回归 | 容器中 pytest 当前复制的 `test_patient_demo_case_closure.py test_case_preparation.py test_case_post_visit_feedback.py test_intent_latency.py -q --tb=short -p no:cacheprovider -o asyncio_mode=auto` | exit 0；32 passed，51 条 datetime 弃用警告 |
| 测试隔离 | 新建 `medaxis_review_20260926_closure`，测试的三个数据库环境变量均指向该库 | 结束后测试库 public 业务表数量为 0；现有 medaxis 的病例/解析任务表仍存在、版本仍为 head |
| 运行代码抽查 | 比较容器及工作区 `patient_case_persistence.py` SHA256 | 一致：`227E9A131A1F96DF578AEC65E3A292CD7968643A35BAA923788F51E43302CBFB` |
| 前端单测 | `npm test -- --run` | 9 passed，0 failed |
| 类型检查 | `node_modules/.bin/tsc.cmd -p tsconfig.app.json --noEmit` | exit 0 |
| 构建 | `npm run build` | exit 0；仍有大于 500 KB chunk 警告 |
| 浏览器回归 | 本轮独立启动 3004；设置 `CHAT_TEST_URL=http://127.0.0.1:3004`，执行 `python tests/chat_history_browser.py` | exit 0；6 组 PASS。API/SSE 为 mock，验证 UI 状态，不证明真实后端端到端 |

本轮启动的 3004 Vite 已停止；一次性审查空库及容器 `/tmp/medaxis_review_tests_20260926` 测试副本保留，未删除现有数据库或用户数据。本轮全仓 ESLint、全量后端、真实外部模型和真实上传解析未复跑。

## 用户手动验收：先验证当前应用

1. 在管理员页面 `/admin/providers` 添加实际可用的供应商，填写 Base URL、模型与 API Key。类型选择“诊断/对话”，平台留空或正确匹配 web，开启激活及默认，保存并测试连接。密钥只填管理页面。连接测试通过仍需实际问诊验证。
2. 在普通应用中新注册一个合成患者。确保前端请求指向当前后端（本机 Docker 后端 8000）；不要打开 `tests.patient_demo_server` 的替身页面来验证真实模型。
3. 输入明确标注为合成演示的主诉，按问题真实作答至少一次，继续至结构化报告。通过标准：问题可回答、没有统一失败提示、报告不是预置文本；保存失败必须显示错误。不要用报告内容判断医学正确性。
4. 点击报告“科室导航与就医准备”，记录地址中的 `case_id`。在“我的病例”找到本次唯一病例，标题、主诉和报告对应本次会话。刷新列表不增加第二个病例。科室目录清楚标为演示，不显示虚构的推荐或预约成功。
5. 生成准备包，核对患者陈述，填写一条待咨询问题，保存；查看版本/修订号。复制摘要到记事本，核对来源说明、未知项以及自己填写的内容一致。
6. 填写一次合成的患者自报就诊时间、科室、情况和复查事项，保存。通过标准：显示保存成功及患者自述标识；准备和反馈仍在步骤 4 的同一病例。
7. 清除该站点 localStorage/sessionStorage，重新登录，从“我的病例”进入。病例数量、报告、核对内容、准备版本和反馈均应恢复；不能依赖旧聊天缓存。可使用新的浏览器隐私窗口登录同一账号进一步验证。
8. 新建第二个合成账号，访问第一个账号的病例链接。页面不得显示对方报告或反馈；相关病例 API 应返回 404/拒绝访问。

前端开发者工具 Network 可以核对 `/patient/cases/{case_id}/recovery`、`/preparation`、`/post-visit-feedback` 都使用同一 ID。不要截图或共享 Authorization 请求头。

## 必补的反例

- 建两个不同合成病例 A/B。DevTools 阻断 B 的 recovery 请求，然后 A→B；B 显示失败，不得留下 A 的准备/反馈操作区。节流网络快速 A↔B 切换，最终画面必须对应最后选择。
- 编辑准备内容后切换 Offline 再保存：必须显示“未保存”，不得增加成功版本；恢复网络后可重试。反馈保存同样验证。
- 用测试夹具中的非空 `red_flags` 验证风险展示位置；无需诱导模型生成危险医疗内容。
- 同一来源会话重复完成：病例数仍为 1。当前 helper 定向回归已验证顺序重复；并发请求及真实 Redis 锁需另测，不能由该结果推出。

## 确定性展示与安全复跑

需要稳定录屏时，可按现有 `demo-runbook.md` 的启动步骤运行隔离演示 API 8012 和前端 3002，并在画面中保留合成演示标识。本机 Docker PostgreSQL 映射是 **5433**，不是示例中的 5432；应使用实际实例端口和自己的本地凭据，先创建全新 `medaxis_demo_e2e_<唯一后缀>` 再迁移。

启动前端建议加 `--strictPort`。E2E 固定期待合成问题/报告，只适用于替身服务，不适用于真实模型验收。

```powershell
# 在 backend 目录，演示服务和前端启动之后
$env:DEMO_API_URL='http://127.0.0.1:8012/api/v1'
$env:DEMO_WEB_URL='http://127.0.0.1:3002'
python tests/patient_demo_e2e.py

# 在 frontend 目录，单独验证 mock UI 回归
$env:CHAT_TEST_URL='http://127.0.0.1:3002'
python tests/chat_history_browser.py
```

**不要复制原 runbook 的“复跑回归”数据库配置。** 如需重跑 pytest，另建空测试库（例如 `medaxis_review_<唯一后缀>`），将 `DATABASE_URL`、`TEST_DATABASE_URL`、`ASYNC_DATABASE_URL` 全部设为该测试库，再运行定向测试。测试允许建表/清表，因此该库不能存放任何需保留的数据。

E2E 脚本每次注册新合成用户并覆盖固定的 `demo-e2e-result.json`；需要保留历史证据时先另存上一份。对账应实际查询 `alembic_version`，并验证 `MedicalCase.source_session_id` 指向此次问诊会话、准备包和反馈的 `case_id` 与病例一致，不能只看 JSON 中固定写入的版本。

## 完成判定

上述手工 1–8 在真实模型环境全部通过后，才可追加“已用真实模型完成患者端主线验收”；此前保留“合成演示闭环”。医生端可以继续延期。个性化科室推荐、医疗内容专业审核、真实机构导航/挂号仍不属于已完成范围。
