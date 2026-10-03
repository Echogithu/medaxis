# 患者共用外壳与问诊内转接医生验收

2026-10-03。以用户最新纠正为范围：仅在 AI 问诊“需要专业帮助？”添加转接真实医生，不新增患者或医生咨询页面、路由、菜单，也不在问诊记录另加入口。此前患者共用外壳优化继续保留。

## 当前行为与位置

- 患者在问诊辅助卡点“转接”，原地弹窗选择认证医生、填写问题、勾选报告解析结果并明确同意共享。提交后在同一问诊页弹窗查看等待接诊、医生回复、补充及取消；刷新恢复进度，关闭回到原对话。未登录或未保存问诊先显示简短前置条件。
- 医生从已有工作台的“患者转接”处理请求，没有新增医生页面或菜单。接受后可发布独立建议，或说明原因婉拒；患者可以保留历史。
- 状态和回复保持真实持久化接口、归属验证、固定资料快照、明确授权、提交去重与版本冲突校验。取消、完成、婉拒或资质失效后停止医生读取共享资料。
- 通知链接改为 `/chat?consultation_id=…` 与 `/doctor?consultation_id=…`，进入上述既有页面。

关键文件：`frontend/src/components/ChatPage.tsx`、`DoctorHandoffDialog.tsx`、`CreateConsultationDialog.tsx`、`ConsultationDetailPanel.tsx`；医生工作台 `frontend/src/doctor/pages/DoctorDashboard.tsx` 与 `frontend/src/doctor/components/DoctorHandoffRequests.tsx`；后端 `backend/app/api/v1/consultations.py`。

患者外壳保持 `PatientLayout` 与内容区 Suspense；会话通过 `chatNavigation` 注册共享侧栏。原独立 `ConsultationsPage.tsx` 已移入本轮活动目录的 `archived/`，不参与构建。

## 本轮实际验证

以下命令均 exit 0：

| 目录 / 命令 | 关键结果 |
| --- | --- |
| frontend / `npx tsc -b` | 类型检查通过 |
| frontend / 对本轮 12 个触及 TS/TSX 文件执行 `npx eslint` | 无 error、warning |
| frontend / `npm test`、`npm run build` | 单元测试、构建成功；构建仍有主入口大于 500 kB 与插件耗时警告 |
| frontend / `CHAT_TEST_URL=http://127.0.0.1:3002 python tests/consultation_sidebar_browser.py` | 转接原地弹窗、未保存前置条件、摘要/报告来源、会话隔离、1024/390/320px 抽屉通过 |
| frontend / 同地址 `python tests/patient_spa_browser.py` | 无 document 请求，顶部栏/侧栏 DOM 保留，延迟模块与身份请求仅内容等待，往返会话保留 |
| backend / `.venv\Scripts\python.exe -m tests.consultations_isolated --browser` | 4 passed；真实 PostgreSQL、认证与双角色 API/浏览器；`CONSULTATIONS_ISOLATED_PASS`；自有容器清理 exit 0 |
| 仓库 / `git diff --check` | 无空白错误；现有行尾转换提示 |

真实双端覆盖：问诊卡转接并确认资料 → 认证医生已有工作台接单/回复 → 患者刷新、补充与取消；婉拒原因、完成确认、320/390px 无溢出；关闭回到原对话，再次点转接恢复最终建议。实际事务提交后丢弃响应验证申请/回复去重；409 冲突保留草稿；医生终态 DOM 清空、读取 API 403，患者历史仍可读。固定快照不授予原件下载，不覆盖 AI 总结。

首次浏览器运行已执行到完成咨询，关闭弹窗动画期间的全页文本断言匹配两处摘要而失败。修正为等待弹窗退出并限定原聊天消息区域后，完整重跑 exit 0；业务实现未因此放宽。

证据：`.ai/tasks/2026-10-03-chat-doctor-handoff-entry/` 日志与桌面/手机截图。手动验收：`.claude/manual-test-patient-shell-doctor-consultations.md`。此前共用外壳、发送控件与注册页面的验收保留在前次活动目录。

## 主线程审查与恢复

重点证伪四点：1. 路由与导航仍残留独立页面——定向检索、构建和问诊弹窗浏览器验证无残留；2. 弹窗关闭丢失原对话或刷新丢失进度——浏览器往返和真实数据恢复通过；3. 跨身份、终态残留资料——API 归属测试与双端终态验证通过；4. 重复提交、并发覆盖或手机控件溢出——响应丢失、409 草稿、窄屏实测通过。

本轮修改前 12 个文件在活动目录 `before/`；独立页面在 `archived/`，验收文档也有修订前副本。恢复时先比较这些快照，仅恢复本轮补丁，保留其他未提交或后续修改；不整库重置。数据库有咨询数据时禁止直接降级删除；空表降级/再升级及非空降级拒绝均已验证。

## 未启用范围

业务数据库没有应用新迁移，生产环境与真人接诊未验证。启用需核对目标库、备份和前置迁移，再应用 `e5f6a7b8c9d0` 并发布后端。本次为异步转接与回复，不包含实时通话、正式诊断/处方、原件下载或邮件/短信。隔离 API 测试存在既有 Notification UTC 默认时间的弃用警告，未修改共享时间模型。