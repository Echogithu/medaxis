# 数据库说明

> 当前工作区数据模型静态视图，核对日期：**2026-10-06**。本轮没有连接数据库或核验运行中的迁移版本；模型/迁移存在不代表已应用到业务库。

## 存储组成

- PostgreSQL 为主要持久化数据库，使用异步 SQLAlchemy 与 Alembic。
- Redis 用于 token blacklist/cache，以及 Celery broker 和 result backend。
- 本地 Compose 使用 pgvector PostgreSQL 镜像，但当前知识块模型把 embedding 存在 JSONB 字段，并在应用服务中计算 cosine similarity。当前源码没有证明知识向量写入 pgvector Vector 列。
- 连接配置见 [db/session.py](../../backend/app/db/session.py)，配置项见 [core/config.py](../../backend/app/core/config.py)。

## 模型分组

| 领域 | 主要模型 | 源码 |
|---|---|---|
| 用户与访客 | User、GuestSession、RoleSwitchLog、UserAttachment | [user.py](../../backend/app/models/user.py) |
| 问诊与患者管理 | AgentSession、AgentTask、PatientHealthProfile、CarePlan、MonitoringEvent | [agent.py](../../backend/app/models/agent.py) |
| 病例与病例文档 | MedicalCase、MedicalDocument | [medical_case.py](../../backend/app/models/medical_case.py) |
| 聊天文件解析 | DocumentParseTask：原件字节、归属、解析状态、结果与会话/病例关联 | [document_parse.py](../../backend/app/models/document_parse.py) |
| 就医准备与自报反馈 | CasePreparationPackage、PatientPostVisitFeedback：来源、修订与历史 | [case_preparation.py](../../backend/app/models/case_preparation.py)、[post_visit_feedback.py](../../backend/app/models/post_visit_feedback.py) |
| 独立检查报告 | PatientReport、文件、处理任务、核对版本、病例引用与提交墓碑 | [patient_report.py](../../backend/app/models/patient_report.py) |
| 知识库 | Document、DocumentChunk、DocumentReview | [rag.py](../../backend/app/models/rag.py) |
| 动态配置 | LLM provider 配置、系统设置 | [config.py](../../backend/app/models/config.py) |
| 运营记录 | 通知、邮件配置/模板/日志、审计日志 | [notification.py](../../backend/app/models/notification.py)、[email.py](../../backend/app/models/email.py)、[audit.py](../../backend/app/models/audit.py) |

完整字段、约束和 relationship 应以相应 SQLAlchemy 模型与迁移为准，不以本页的概述代替 schema。

## 文件与版本存储

聊天解析原件保存在 DocumentParseTask.file_bytes，新报告原件保存在 PatientReportFile.content（LargeBinary）。不能用“没有上传文件卷”推断数据库里的新报告原件会随容器重建丢失；数据库卷和备份仍需保护。

新报告中心将原件、AI 候选、人工核对版本与病例引用分开，回收站/恢复/彻底删除有独立提交记录。删除平台记录不代表备份或外部已发送内容已同时清除；实现及迁移边界见[报告需求](../product/PATIENT_REPORTS_REQUIREMENTS.md)。

演示开关、身份及额度使用 system_settings；重复准备和重启不重置计数，操作见[面试演示说明](../INTERVIEW_DEMO.md)。

## AgentSession 与诊后对话

AgentSession 保存会话类型、状态、用户/访客归属、上下文、结构化输出和工具调用记录。context 与 structured_output 使用 JSONB；诊后对话 session 可通过 parent_session_id 关联到父诊断会话。

该父子关系支持把后续聊天作为独立记录保存。实际所有权和访问权限仍需依据 endpoint 逐一核验。模型定义见 [agent.py](../../backend/app/models/agent.py)。

## 医疗知识检索的存储边界

DocumentChunk 保存文档块文本及 JSONB embedding。RAG 服务独立执行关键词和同模型向量召回，在应用层流式扫描向量并计算相似度，合并后可选使用 reranker；当前尚无向量索引。见 [rag.py](../../backend/app/models/rag.py) 与 [rag.py service](../../backend/app/services/rag.py)。

依赖 pgvector 或使用 pgvector 镜像，不代表模型已采用数据库原生向量列。发生存储方式变化时，应同步更新模型、迁移、查询逻辑和本页说明。

## 迁移与验证

Alembic 配置及迁移位于 [backend/app/db/migrations](../../backend/app/db/migrations)。本次没有读取运行数据库、执行 alembic current/upgrade 或确认部署环境的 migration head；上线状态应以目标环境的迁移检查为准。

建议的本地结构检查入口：

~~~sh
cd backend
alembic heads
alembic current
~~~

`alembic heads` 读取迁移脚本，不连接业务库；`alembic current` 需要数据库配置。本轮未运行。

数据库测试要求三个 URL 一致，库名为 `medaxis_test_*`，并显式设置 `MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB=1`；fixture 会建表/删表。浏览器演示库 `medaxis_demo_e2e_*` 不能交给该 fixture。完整约束见[测试安全护栏](../../backend/tests/database_safety.py)。
