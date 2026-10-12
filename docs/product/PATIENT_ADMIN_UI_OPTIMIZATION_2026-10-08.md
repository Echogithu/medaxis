# 患者端与管理员界面优化验收

2026-10-08。依据同日《患者端与管理员后台界面审查》，用户授权修改确定问题 02–16，明确排除 01 问诊麦克风。本轮已完成本地界面实现及合成接口验证；不代表真实后端、模型、邮件或医疗效果通过验收。

## 用户能感知的变化

| 审查编号 | 修改后的行为 | 关键文件（frontend/src 下） |
|---|---|---|
| 02 | 上传前显示单文件 10MB 限制；超限明确提示文件名，保留输入 | components/ChatInput.tsx |
| 03 | 报告中心就绪时进入检查报告；演示环境未就绪时明确进入“病例附件” | patient/pages/HealthProfilePage.tsx、FollowUpPage.tsx |
| 04 | 访客失败留在登录页；聊天读取失败可页内重新加载 | auth/LoginPage.tsx、components/ChatHistoryPage.tsx |
| 05 | 用户和医生列表支持连续翻页；显示本页数量，不冒充总数 | admin/pages/UsersPage.tsx、DoctorVerificationPage.tsx |
| 06 | 站内信筛选与重置均回第一页 | admin/pages/NotificationsPage.tsx |
| 07 | 数组接口多取一条判断下一页；去掉估算总页数 | admin/components/AdminListPager.tsx、pages/KnowledgeBasePage.tsx、ReviewQueuePage.tsx、AuditLogsPage.tsx |
| 08 | 手机随访统计并排显示，保留来源和部分加载说明，让待办更早出现 | patient/pages/FollowUpPage.tsx |
| 09 | 手机用户、医生、模型表格固定名称和操作列；模型测试放在操作列 | admin/mobileActionTableSx.ts、pages/UsersPage.tsx、DoctorVerificationPage.tsx、LLMProvidersPage.tsx |
| 10 | 设置优先显示中文说明，技术信息按需展开；模型导航统一“AI 模型配置”；站内信类型和优先级显示中文 | admin/pages/SystemSettingsPage.tsx、LLMProvidersPage.tsx、NotificationsPage.tsx、layout/AdminLayout.tsx |
| 11 | 用药记录分“正在服用”和“已停用”，卡片展示药名、剂量、频率和来源 | patient/pages/HealthProfilePage.tsx |
| 12 | 提醒空状态进入“查看用药清单”，说明清单和提醒分别管理 | patient/pages/MedicationReminderPage.tsx |
| 13 | 今日超过四项时可“查看其余 N 项”，也可收起 | patient/pages/TodayHealthPage.tsx |
| 14 | 随访日历标题改为“未来 7 天安排”，日期仍逐日展示 | patient/pages/FollowUpPage.tsx |
| 15 | 补审核状态、操作人 ID、失败邮件和收件人/主题筛选 | admin/pages/KnowledgeBasePage.tsx、AuditLogsPage.tsx、EmailManagementPage.tsx |
| 16 | 档案错误标到字段并聚焦，保存失败保留草稿；邮件错误持续显示，可重新加载 | patient/pages/HealthProfilePage.tsx、admin/pages/EmailManagementPage.tsx |

附带修正：设置切换分类不再重新读取并覆盖草稿；列表读取失败清空旧页结果，避免把上页记录放在新页码下。医生原“待审核”实际查询所有未认证医生，包括未通过，现更名为“未认证”并解释范围；没有改变后端筛选规则。

未改变：麦克风代码、已接受的问诊总结顺序、注册必填、省份收集、注册后落点、任务完成规则、找回账号流程、权限、外发同意、医疗内容、API/schema/数据库、依赖。没有提交、推送或部署。

## 验证证据

以下命令均在本轮实际执行。浏览器全部接管 `/api/v1/`，只使用合成身份、记录、报告和错误；保存重试也是模拟响应。

| 检查 | 命令（frontend 目录） | 结果 |
|---|---|---|
| 单元测试 | `npm.cmd test` | exit 0，93 项通过、0 失败 |
| 类型检查 | `npx.cmd --no-install tsc -b --pretty false` | exit 0 |
| 生产构建 | `npm.cmd run build` | exit 0；仍有大于 500kB 的包体提示 |
| 新增界面回归 | `python tests/ui_optimization_browser.py` | exit 0：107 条记录、数组末页、第二页筛选重置、报告条件入口、失败重试、字段聚焦、保存失败保留草稿、设置切分类草稿、今日展开、窄屏操作列 |
| 患者外壳回归 | `python tests/patient_shell_browser.py` | exit 0：导航、会话保留、用药分组、未知状态、320/390/768 布局 |
| 今日健康回归 | `python tests/today_health_browser.py` | exit 0：提醒打卡刷新、空态、部分加载、登录/访客边界、320/390/768 输入无遮挡 |
| 问诊总结回归 | `python tests/consultation_optimization_browser.py` | exit 0：1440/390/320 总结排序、来源引用、补充追问、历史恢复 |
| 改动文件 Lint | `npx.cmd --no-install eslint <本轮源码文件>` | exit 1：28 个既有错误、2 个警告。与修改前快照对照，原为 29 个错误、2 个警告，按文件/规则/消息首行比较无新增诊断；不能称 Lint 全部通过 |
| 范围与恢复 | 比对麦克风状态和按钮；`git apply --reverse --check --ignore-space-change .ai/tasks/2026-10-08-ui-optimization/this-turn.patch`（根目录） | 两项 exit 0，麦克风逐字一致；仅检查反向补丁可用，未执行恢复 |

测试启动方式：

```powershell
# 终端一：frontend
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3001 --strictPort

# 终端二：frontend
$env:CHAT_TEST_URL='http://127.0.0.1:3001'
$env:PYTHONIOENCODING='utf-8'
python tests/ui_optimization_browser.py
python tests/patient_shell_browser.py
python tests/today_health_browser.py
$env:REPORT_SCREENSHOT_DIR='D:\CAI-Projects\medaxis\.ai\tasks\2026-10-08-ui-optimization\summary-screenshots'
python tests/consultation_optimization_browser.py
```

本轮截图、Lint 现状/基线、恢复快照和源文件反向补丁位于 `.ai/tasks/2026-10-08-ui-optimization/`。截图用于人工抽查，断言也检查了数据就绪和操作列边界。主代理查看了手机模型表格、随访及档案截图。两组只读复核未发现可确认的新增缺陷；复核是源码审查，没有连接真实服务。

测试过程中修正了加载占位行等待、路由名称、重复文字定位、通知 URL 尾部斜杠和既有按钮名称断言；保留真实失败/末页/保存行为断言，没有删掉失败用例来取得通过。

## 风险与恢复

最可能失败的点及处理：

1. 超过一页时漏记录或最后一页无限前进：使用 107 条用户/医生、23 条知识/审核、45 条审计合成数据验证，不估算总数；未验证线上并发增删时的快照一致性。
2. 更换筛选后旧请求覆盖新结果：用户/医生使用取消标记，知识/审核/审计/邮件使用请求序号；列表失败不显示上一页旧结果。未覆盖所有管理员弹窗及所有网络时序。
3. 手机操作被横向表格或底部导航遮住：验证 320/390/768，固定名称/操作列，既有患者输入导航回归通过；未做完整读屏和管理员暗色主题专项。
4. 长表单失败后失去内容或错误找不到：验证空疾病字段聚焦、失败保留填写及模拟重试成功；未知服务端校验仍显示总错误，不擅自映射到错误字段。
5. 报告入口在演示环境承诺不可用功能：分别验证就绪和未就绪分支；未执行真实报告处理。

恢复只针对本轮差异：源文件可先检查上述反向补丁，并结合 `original/` 快照人工核对；新分页组件、样式文件和新增回归测试单独处理。两份既有浏览器测试只调整与当前文案、入口对应的断言，恢复时按这些小段处理。不要对整个工作区执行 `git restore` 或 `reset`，以免覆盖本轮之前已有的修改。

人工验收清单位于 `.claude/manual-test-ui-optimization.md`。真实后端联调、真实设备阅读体验、读屏和暗色模式为剩余验收；01 麦克风按用户指示暂不处理。
