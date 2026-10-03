# 健康档案与随访工作区验收

日期：2026-10-03。交付范围为源码与隔离环境验收，未部署、未迁移当前业务库。

## 变更

依据患者工作区原型重排 `/health` 与 `/followups`，沿用既有 Teal/Slate 设计规范和共同患者页面外壳。原型的演示数据及不受现有接口支持的出生日期、家族史、医生与预约信息不写入产品。

- 健康档案：患者摘要、基础资料、彩色状态与疾病标签、过敏记录、用药表；档案与清单复用一个带版本保护的编辑弹窗。右栏新增最新健康指标、历史记录与就诊资料入口。
- 指标记录：独立 `/api/v1/patient/measurements` API 和 `patient_health_measurements` 表，追加保存血压、心率、体重和测量时间；患者权限、所有权隔离、严格数值/时间校验、重复请求去重和分页。记录不覆盖基础档案体重或版本。
- 随访：进行中概览、筛选页签、计划进度和任务勾选；自测勾选与填写反馈复用弹窗，症状变化与反馈必填，用药情况和数值可选。普通复查任务可直接确认完成；成功才更新勾选。反馈保存至既有 `completion_notes` 和数值字段，不自动交付医生。
- 日历来自实际进行中任务；概览最多加载 50 个进行中计划，超过时标明范围。原有创建、编辑、确认、暂停、恢复、取消与分页保留。

## 验证证据

命令均在项目对应目录运行，隔离脚本只启动任务自己的临时数据库、API、Vite 和 Edge，退出后清理自身容器与进程。

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m tests.profile_chain_isolated`（backend 目录） | exit 0；64 passed；迁移往返、档案 API 与浏览器闭环通过 |
| `.venv/Scripts/python.exe -m tests.profile_chain_isolated --browser-only`（backend 目录，最终页面） | exit 0；`PROFILE_CHAIN_ISOLATED_PASS`；无浏览器运行时异常 |
| `.venv/Scripts/python.exe -m tests.followup_chain_isolated`（backend 目录） | 接口阶段 exit 0，28 passed；首次浏览器阶段失败，后续修正验收定位与等待方式并独立重跑 |
| `.venv/Scripts/python.exe -m tests.followup_chain_isolated --browser-only`（backend 目录） | exit 0；`FOLLOWUP_CHAIN_ISOLATED_PASS`；反馈、直接勾选失败/重试、刷新、状态与分页闭环通过，无运行时异常 |
| `npx tsc -b`、针对本次页面/组件/API/测试的 `npx eslint`（frontend 目录） | exit 0 |
| `npm test`（frontend 目录） | exit 0；68 passed，含 3 个新增指标请求/异常契约测试 |
| `npm run build`（frontend 目录） | exit 0；保留主入口约 631KB 的构建体积提醒 |
| `CHAT_TEST_URL=http://127.0.0.1:3002 python tests/patient_shell_browser.py`（frontend 目录，PowerShell 用环境变量赋值） | exit 0；页面外壳、标签状态与 320/390/768px 回归通过 |

日志、合成数据截图及修改前副本保存在 `.ai/tasks/2026-10-03-health-followup-workspace/`；人工验收见 `.claude/manual-test-health-followup-workspace.md`。

## 自我审查与边界

1. 原型状态不等于业务事实：没有复制演示患者、病史或医生；日历与统计来自实际 API，部分加载明确标注。
2. 勾选与反馈不能伪成功：请求失败保留草稿及未完成状态；成功使用服务端返回计划更新，最后任务完成状态由服务器决定。浏览器注入 500/409 验证。
3. 新指标不能覆盖既有健康档案：单独持久化，并验证写入后基础体重、档案版本不变；同一请求重试只有一条记录。
4. 移动端长字段与弹窗溢出：320/390/768px 验证页面与反馈弹窗，桌面视觉检查卡片对齐。不同真实数据、设备字体和键盘操作仍需部署环境人工抽验。
5. 业务库尚未启用指标表：新迁移 `7d2c9e4a1b60` 接在 `e5f6a7b8c9d0` 后，目标环境需检查整条待执行迁移链并备份后应用。隔离迁移成功不等于业务库已经迁移。

## 恢复

对照 `.ai/tasks/2026-10-03-health-followup-workspace/before/` 逐文件恢复本次已有文件改动，新增文件单独移至任务归档目录；不得执行全仓 reset 或覆盖其他未提交工作。当前业务库未修改，无数据库回退动作。启用后有指标历史时，迁移 downgrade 会拒绝直接删除表，须先制定保留数据的迁移方案。
