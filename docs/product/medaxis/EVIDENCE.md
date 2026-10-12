# MedAxis 项目事实与覆盖矩阵

> Status: REVIEW · 核对日期：2026-10-09 · 类型：静态源码与历史证据审阅
>
> 基线 HEAD：`1b95d41a65f493274a8b7ae47e8cdede7e45d539`，分支 master。工作区已有大量未提交改动；本包描述核对时工作区，不等于该 HEAD 或公开克隆已具备全部能力。

## 1. 覆盖与证据层级

本次检查三条范围：患者路由/状态/API；AI 编排/检索/报告处理与评测记录；医生/管理角色与运营 API。核心源码树共 265 个文件（读取文件清单计数），并未逐一穷尽所有分支。当前应用实例、数据库、配置、模型、索引和供应商账单未读取或运行。

**工作区同期变化：** 最后范围检查发现6个AI评测/来源筛选相关既有文件与开工哈希不同，非本任务写入路径。主代理于2026-10-09 21:09（UTC+8）复核新增记录及相关服务，补入下方问题覆盖v3证据；其他分端结论未用旧哈希冒充最终全工作区快照。变动来源未核实，不自动回滚；清单留在本机任务scope-results.json。

| 层级 | 本次可用证据 | 允许结论 |
|---|---|---|
| 源码 | 路由、服务、模型和测试源码；下表定位 | 存在实现或可定位差距 |
| 历史自动化/集成 | 带日期验收与隔离记录 | 只在其样本与环境成立，不是本轮重跑 |
| 当前目标环境 | 本轮 NOT_RUN | 不声明当前部署可用 |
| 真人/专业验证 | 缺少可引用的完整证据 | 不声明真实患者价值或临床有效性 |
| 发布 | 无本轮发布动作 | 不声明上线或生产准备完成 |

系统组成参考 [architecture](../../engineering/architecture.md)：React/MUI 前端、FastAPI API、PostgreSQL 持久层、Redis/Celery 异步任务；模型、检索与本地 OCR 是不同依赖。这里的组成关系是静态架构，不是当前运行图。

## 2. 源码证据索引

链接定位核对日期附近的行；后续源码变化应按符号重新定位。E 编号是事实引用索引，不替代需求编号。

| ID | 已看到的行为 / 限制 | 精确抓手 |
|---|---|---|
| E-01 | 公共/患者/医生/管理路由；前端 RequireRole 允许 admin 绕过角色页面限制，不等于后端授权 | [`App.tsx RequireRole/Routes`](../../../frontend/src/App.tsx#L52)；API 挂载 [`v1/__init__.py`](../../../backend/app/api/v1/__init__.py#L18) |
| E-02 | 浏览器聊天按身份保存；无 server file_id 的处理中上传刷新后失败；会话 user/guest 归属检查 | [`chatHistory.ts`](../../../frontend/src/state/chatHistory.ts#L41)、[`agents.py _require_session_access`](../../../backend/app/api/v1/agents.py#L109) |
| E-03 | 主入口流式路由、诊断完成保存；题目语义去重失败保留候选，不是 RAG 召回 | [`agents.py`](../../../backend/app/api/v1/agents.py#L1026)、[`orchestrator.py _semantic_dedup`](../../../backend/app/services/orchestrator.py#L621) |
| E-04 | 病例保存按来源会话支持幂等；本人病例恢复、材料过滤 | [`patient_case_persistence.py`](../../../backend/app/services/patient_case_persistence.py#L23)、[`patient.py`](../../../backend/app/api/v1/patient.py#L343) |
| E-05 | 就医准备 revision 冲突 409；当前会话内存草稿刷新不恢复 | [`patient.py`](../../../backend/app/api/v1/patient.py#L523)、[`casePreparation.ts`](../../../frontend/src/state/casePreparation.ts#L4) |
| E-06 | 诊后反馈版本/追加历史；档案 revision；测量 request_id 冲突 | [`patient.py`](../../../backend/app/api/v1/patient.py#L722)、[`patient_profile.py`](../../../backend/app/services/patient_profile.py#L111)、[`health_measurements.py`](../../../backend/app/api/v1/health_measurements.py#L58) |
| E-07 | 计划本人归属、创建指纹、任务首次记录；sent 提醒才可确认，重复确认幂等 | [`care_plans.py`](../../../backend/app/api/v1/care_plans.py#L53)、[`care_plan.py`](../../../backend/app/services/care_plan.py#L95)、[`patient.py`](../../../backend/app/api/v1/patient.py#L853) |
| E-08 | 新报告角色/归属、上传请求指纹与 metadata revision；上传待保存文件仅页面内存 | [`patient_reports.py`](../../../backend/app/api/v1/patient_reports.py#L79)、[`ReportUploadDialog.tsx`](../../../frontend/src/patient/components/ReportUploadDialog.tsx#L46) |
| E-09 | 草稿、确认历史分开；病例链接固定 source/review version 并标记变化 | [`report_review.py`](../../../backend/app/services/report_review.py#L123)、[`report_links.py`](../../../backend/app/services/report_links.py#L17) |
| E-10 | 诊后候选同意、原文约束、排程、停用和来源变更语义 | [POST_VISIT_AI_ACTIONS_SPEC](../POST_VISIT_AI_ACTIONS_SPEC.md)；属于详细行为与历史验收入口，本轮未重跑 |
| E-11 | 咨询仅患者/认证 active 医生；对象归属、快照指纹、单活动咨询、消息幂等与撤销 | [`consultations.py doctor_available/owned_consultation`](../../../backend/app/api/v1/consultations.py#L32)、[`create_consultation`](../../../backend/app/api/v1/consultations.py#L120)、[`Consultation ACTIVE_STATES`](../../../backend/app/models/consultation.py#L13) |
| E-12 | 旧医生 helper 仅检查医生角色；列表/详情按患者查会话；部分统计/risk 固定；plan 501 | [`doctor.py _require_doctor`](../../../backend/app/api/v1/doctor.py#L29)、[`list_doctor_cases`](../../../backend/app/api/v1/doctor.py#L98)、[`get_case_detail`](../../../backend/app/api/v1/doctor.py#L159)、[`send_plan_instruction`](../../../backend/app/api/v1/doctor.py#L214) |
| E-13 | 旧医生详情混入 MOCK_CASE patient_info/timeline/structured_report；评论客户端有请求而本次 doctor 路由未定位 handler | [`CaseDetailPage.tsx MOCK_CASE`](../../../frontend/src/doctor/pages/CaseDetailPage.tsx#L80)、[`load`](../../../frontend/src/doctor/pages/CaseDetailPage.tsx#L161)、[`doctor.ts`](../../../frontend/src/api/doctor.ts#L66) |
| E-14 | RAG 两路独立候选并集、同模型 cosine 排序，重排失败保留；空 search_terms 提前返回，向量 ValueError 降为关键词 | [`rag.py RAGService.search`](../../../backend/app/services/rag.py#L237)、[独立召回](../../../backend/app/services/rag.py#L279) |
| E-15 | 缺来源/无有效引用不发布；来源要点判断有降级，相关与覆盖不等于原文支持 | [`agents.py`](../../../backend/app/services/agents.py#L869)、[`knowledge_citations.py rank_knowledge_citations`](../../../backend/app/services/knowledge_citations.py#L313) |
| E-16 | 旧问诊 documents 上传字节入任务；视觉/文件模型可能接收原件 | [`documents.py`](../../../backend/app/api/v1/documents.py#L74)、[`tasks/documents.py`](../../../backend/app/tasks/documents.py#L66) |
| E-17 | 新报告本地取字 worker 禁网；发送绑定预览/来源/接收方且只发文字；失败不自动重发 | [`report_text_worker.py`](../../../backend/app/services/report_text_worker.py#L22)、[`report_processing.py`](../../../backend/app/services/report_processing.py#L157) |
| E-18 | 普通 guest 提交额度与过期；面试模式每个 provider HTTP 尝试持久扣减、失败不退、limit1–20 | [`guest_model_quota.py`](../../../backend/app/services/guest_model_quota.py#L113)、[`interview_demo.py load_policy/reserve_provider_request`](../../../backend/app/services/interview_demo.py#L40) |
| E-19 | admin router 后端统一角色依赖；非 active token 拒绝；最后 admin 保护；kick 实际 db.delete | [`admin.py`](../../../backend/app/api/v1/admin.py#L47)、[`deps.py`](../../../backend/app/api/deps.py#L84)、[`admin.py kick_user`](../../../backend/app/api/v1/admin.py#L812) |
| E-20 | 医生审核邮件失败记日志，但成功文字仍称已发送；审计不代表每个操作都有记录 | [`admin.py`](../../../backend/app/api/v1/admin.py#L906)、[`AuditService`](../../../backend/app/services/audit.py#L17) |
| E-21 | 知识/提供方/邮件/通知管理接口存在；没有本次逐表单联调证据 | [`admin.py`](../../../backend/app/api/v1/admin.py#L279)、[`email.py`](../../../backend/app/api/v1/email.py#L53)、[`notifications.py`](../../../backend/app/api/v1/notifications.py#L62) |

## 3. 页面覆盖矩阵

覆盖 `App.tsx` 所声明路由，含默认重定向。API 前缀均为 `/api/v1`；下表前端权限是呈现规则，后端权限见证据索引，不混为一谈。管理页具体字段及所有失败分支属于未穷尽范围。

| 页面路由 | 动作 / 数据 | 状态与失败 | 角色 / 对象范围 | 证据 / 覆盖深度 |
|---|---|---|---|---|
| `/` | 身份入口或主页跳转 | 已登录跳对应角色；未登录入口 | 公共 | E-01，路由级 |
| `/login` | 登录 | 凭据/状态错误；当前运行未验 | 公共 | E-01，路由级 |
| `/register` | 普通注册 | 演示模式关闭公开注册 | 公共/模式约束 | E-01/E-18，路由与服务 |
| `/chat` | AI 采集、材料、咨询面板 | SSE/保存失败；本地历史恢复 | 患者或 guest；后端校验会话归属 | E-02/03/11，链路级静态 |
| `/today` | 档案、任务、提醒、病例聚合 | 各区独立失败/重试 | 患者页面；API 本人范围 | [`TodayHealthPage`](../../../frontend/src/patient/pages/TodayHealthPage.tsx#L32)，E-01/04/07 |
| `/health` | 档案和测量 | 未知/无、revision 冲突 | 本人档案；测量要求患者 | E-06，链路级静态 |
| `/followups` | 计划/候选、执行任务 | 待确认/active/paused/终态 | 患者本人计划 | E-07/10 |
| `/reminders` | 查看与确认 | sent 方可确认；送达≠执行 | 患者本人事件 | E-07/10 |
| `/cases` | 列表、准备、反馈、恢复 | URL 选择、加载/冲突/草稿 | 本人病例 | E-04/05/06 |
| `/reports` | 报告列表、上传、筛回收站 | 归档/处理中/失败/回收 | 患者本人报告 | E-08/09/17 |
| `/reports/:reportId` | 原件、AI、草稿、核对、关联 | 多状态轴、旧预览/修订冲突 | 本人报告及本人病例 | E-08/09/17 |
| `/doctor` | 工作台及定向咨询 | 部分硬编码统计；咨询资格重查 | 页面 doctor/admin bypass；API 各自判定 | E-01/11/12，局部静态 |
| `/doctor/cases` | 分配病例列表 | 固定 risk_level；非完整咨询列表 | 后端 assigned doctor | E-12 |
| `/doctor/cases/:caseId` | 详情/评论/计划输入 | MOCK_CASE 混入；评论缺 handler/plan501 | 分配病例；患者全量会话查询范围疑点 | E-12/13 |
| `/admin` | 仪表盘 | 统计与依赖状态待逐项联调 | admin API | E-01/19/21，路由级 |
| `/admin/users` | 查询/修改/踢用户 | 最后 admin 保护；踢为删除 | admin | E-19，关键操作静态 |
| `/admin/doctors` | 审核资格 | 邮件结果不可信；拒绝含删除 | admin | E-20 |
| `/admin/providers` | 模型提供方配置 | 连接/保存失败未逐操作验 | admin | E-21，接口级 |
| `/admin/settings` | 系统配置 | 配置状态/失败未逐操作验 | admin | E-21，接口级 |
| `/admin/knowledge` | 上传与检索资料管理 | 解析/索引/审核状态 | admin | E-14/21，接口级 |
| `/admin/reviews` | 审核队列 | 审核结果、驳回失败未逐项验 | admin | E-21，接口级 |
| `/admin/audit-logs` | 筛选审计记录 | 空/分页/过滤；覆盖不完整 | admin | E-20 |
| `/admin/notifications` | 通知/广播/读取 | 发送方/接收方软删；业务状态独立 | admin API 各操作规则 | E-21，接口级 |
| `/admin/email` | 配置、模板、日志与发送 | SMTP 未测试；不可承诺送达 | admin | E-21，接口级 |
| `*` | 未知路由重定向 | 返回 `/` | 公共路由策略 | E-01 |

**范围内未定位的规划能力：** 在 frontend/src、backend/app/api/v1、models、services 搜索 institution/research/export/case library/病例库/科研/导出，未定位机构级病例库或研究导出页面/API。ResearchAgent 与报告 institution 字段不等于这两项能力；仓库其他范围不据此作否定结论。

## 4. 历史证据，保留代价与失败

| 记录 | 可引用结果 | 必须一起保留的限定 |
|---|---|---|
| [语义召回 2026-10-08](../SEMANTIC_RECALL_ACCEPTANCE.md) | 同45题/4文档125片段；40正例完整覆盖28/40→32/40，跨语言0/5→4/5 | 4/5无答案仍返回候选；缓存检索P50/P95 69.97/91.14→170.37/191.71ms；专业gold审核0；不是页面/临床准确率 |
| [原文支持评测](../EVIDENCE_SUPPORT_EVALUATION.md) v4 / 2026-10-09 | 53题冻结回归，36执行、17能力缺失、0异常；语义准确率 null | 该次没有额外模型/HTTP；专业审核0；v3的52题和baseline-v2属于旧版本，不能替换v4 |
| [问题覆盖优化更新](../EVIDENCE_SUPPORT_EVALUATION.md) / query-assessment-v3 | 给定候选：开发分类24/24、v4问题相关性切片15/16；完整/部分回答保留，无关误保留开发8→0、回归6→0 | 同语料非盲测；NG143仍误判；24次成功模型调用、23,957服务tokens，金额未知；每组中位1.726秒，非完整问诊；新问诊/API/保存刷新待验。不是Recall@K、原文陈述支持或临床正确率 |
| [报告切片](../PATIENT_REPORTS_REQUIREMENTS.md) 2026-10-06复核 | T1–T5有合成隔离API/DB/OCR/队列/页面证据，去重与引用有实现 | T6组合、实拍OCR、Linux、真实模型质量待验；当日记录演示库未迁移，本轮未复核部署 |
| [诊后候选](../POST_VISIT_AI_ACTIONS_SPEC.md) | 有隔离验收方法、同意/原文/幂等/来源变更场景 | 合成替身不证明真实模型、SMTP、长期任务和部署 |
| [OpenMed规则借鉴](../OPENMED_BORROWING_ACCEPTANCE.md) | 原话语境、核对、遮蔽的规则集成记录 | 不代表真实SDK接入或完整语义理解 |
| [OpenMed SDK独立实验](../../../evals/openmed-transfer/SDK_RESULTS.md) | HOLD；24题非盲测，SDK断言19/28；隐私字符92/101、误遮23；数值/时长保留6/14 | 不接生产、无临床审核；CPU中位约37.1ms/加载约4.8秒不能作为产品性能基线 |
| [展示素材](../../media/README.md) 2026-10-09 | 当前前端合成API/SSE预置重放，9状态GIF和9PNG | 无模型/实际检索/业务库写入；不能证明恢复成功或真实授权 |

底层本机 v4 原始记录：`../../..` 下 `.ai/tasks/2026-10-09-evidence-support/baseline-v4-authorized/REPORT.md`；属于未随文档分发的过程材料。公开阅读优先使用上表稳定验收摘要，缺本机材料不伪造逐题复跑证据。

## 5. 已发现的漂移与待核对

1. 工程 backend/database 的“先关键词再 embedding”概述早于独立语义召回；本次以 E-14 为现状，未来工程同步应回链语义实验。此次不修改工程实现文档。
2. DOCTOR_PRD 的 10月3日 Current Product 是当日事实；当前新咨询已存在，不能重复宣称整条回复联通未实现。旧病例页问题仍成立。
3. docs 素材旧导航称占位，与现有 media/README 的录制记录不一致；本次仅修导航。
4. v4无额外模型调用是早先基线；同期新增query-assessment-v3已记录真实模型配对实验与最小接入。两者是不同阶段，不能以早先自然降级否定新实验，也不能把离线回放/模型实验升级成当前页面和数据库验收。最终运行态仍未核对。
5. consultation_action 的 end 分支目前未显式限制医生角色；目标医生结束与患者取消的操作归属需单独核对，不以流程示意图作为权限证明。

未覆盖：所有 provider adapter 出口、完整消息/日志数据流、管理端每个表单、数据库级全约束、当前实例配置/迁移、真实供应商处理、所有 SSE/异步中断分支。全项目文档覆盖不等于所有代码逐分支审计。
