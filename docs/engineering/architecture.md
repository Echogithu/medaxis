# 系统架构

> 当前工作区实现视图，静态核对日期：**2026-10-06**。此图展示源码责任边界；代码存在不代表迁移、外部依赖或完整链路已在目标环境验收。

## 系统组成

~~~mermaid
flowchart TD
  User[患者、医生或管理员] --> Web[React Web 应用]
  Web --> API[FastAPI API 与 SSE]
  API --> Auth[身份与权限依赖]
  API --> Agents[问诊与 Agent 服务]
  API --> Patient[患者、病例与管理服务]
  API --> Reports[独立检查报告与核对]
  Reports --> DB
  Reports --> Worker
  Agents --> LLM[OpenAI 兼容模型服务]
  Agents -. 按配置调用 .-> Search[可配置的 SearXNG 外部搜索]
  Agents --> RAG[医学知识检索]
  API --> DB[(PostgreSQL)]
  RAG --> DB
  API --> Redis[(Redis)]
  Worker[Celery Worker 与 Beat] --> Redis
  Worker --> DB
  Web -->|SSE| API
~~~

代码入口分别见[前端路由](../../frontend/src/App.tsx)、[FastAPI 装配](../../backend/app/main.py)、[v1 路由聚合](../../backend/app/api/v1/__init__.py)与 [Agent 服务](../../backend/app/services/agents.py)。

## 问诊与诊后对话

~~~mermaid
sequenceDiagram
  actor Patient as 患者或访客
  participant Web as React 前端
  participant API as FastAPI
  participant Agent as 问诊服务
  participant Search as RAG 与 SearXNG
  participant DB as PostgreSQL
  participant Model as 模型供应商

  Patient->>Web: 提交主诉或回答问诊卡
  Web->>API: 请求问诊 SSE
  API->>Agent: 分类意图并启动问诊
  Agent->>Model: Track1 采集信息与生成补问
  Model-->>Agent: 返回问题或采集结果
  opt 达到当前阶段的检索条件
    Agent->>Search: 检索参考资料
    Search-->>Agent: 返回可用结果或空来源
    opt 存在检索结果
      Agent->>Model: Track2 搜索增强补问
      Model-->>Agent: 返回补问结果
    end
  end
  opt 进入报告生成阶段
    Agent->>Model: 请求结构化辅助报告
    Model-->>Agent: 返回候选结果
    Agent->>Agent: 核对来源与发布门禁
  end
  Agent->>DB: 保存会话上下文和结果
  Agent-->>Web: 发送文本、问题、结果或错误事件
  Patient->>Web: 在完成后继续追问
  Web->>API: POST 会话 chat 接口
  API->>DB: 读取父诊断与已有对话
  API-->>Web: 以 SSE 分块返回回答
~~~

主入口包括 /api/v1/agents/route/stream、续答 /api/v1/agents/route/stream/continue，以及诊断后独立对话 /api/v1/agents/sessions/{id}/chat。具体调用方式见[后端参考](./backend.md)。

## 会话与报告

- 问诊会话保存结构化结果和上下文；诊断后追问以子会话关联父诊断，避免把追问记录覆盖到诊断会话中。模型定义见 [AgentSession](../../backend/app/models/agent.py)。
- 聊天报告解析、病例附件与独立报告中心是三种入口。聊天解析将原件、归属和任务状态保存在 [DocumentParseTask](../../backend/app/models/document_parse.py)，由 [Celery 任务](../../backend/app/tasks/documents.py)处理，结果按 `file_id` 轮询；已具备持久状态，进程中断与重复投递仍需故障注入验证。
- 聊天旧解析可能将原图或文件发给模型/文件服务；独立报告中心将原件存入数据库，平台内取字，再按脱敏预览与逐次同意发送文字。归档、AI 候选、人工草稿、核对历史与病例引用分开；见[报告需求与现状](../product/PATIENT_REPORTS_REQUIREMENTS.md)。当前本机演示缺少新版报告中心迁移，不能把这张图当作部署证明。
- PostgreSQL 保存账户、病例、会话、知识库及管理数据；Redis 也用于 token blacklist/cache、Celery broker/result backend。表与存储边界见[数据库说明](./database.md)。
- 浏览器聊天历史使用 localStorage；已保存的病例、准备与自报反馈另由患者 API 恢复。病例恢复不等于完整聊天历史跨设备同步；见[前端说明](./frontend.md)。

## 运行模式

普通模式保留患者/访客及多角色入口。专用面试演示模式仅开放绑定的普通患者账号，关闭访客、公开注册和直接模型调试；供应商 HTTP 请求共享持久化额度，后台没有演示身份的 AI 调用暂停。模式由数据库设置与 [InterviewDemoMiddleware](../../backend/app/services/interview_demo.py)控制，保留原 JWT 和对象鉴权；操作及带日期的验证见[面试演示说明](../INTERVIEW_DEMO.md)。

## 模块分层

| 层 | 主要职责 | 代码位置 |
|---|---|---|
| 表现层 | 登录注册、聊天、患者健康管理、医生工作台、管理后台 | [frontend/src](../../frontend/src) |
| API 层 | REST、SSE、认证/权限依赖、输入输出 Schema | [backend/app/api/v1](../../backend/app/api/v1) |
| 应用与领域服务 | 意图分类、问诊编排、模型调用、RAG、邮件和业务配置 | [backend/app/services](../../backend/app/services) |
| 数据层 | SQLAlchemy 模型、数据库会话、Alembic 迁移 | [backend/app/models](../../backend/app/models)、[迁移目录](../../backend/app/db/migrations) |
| 异步任务 | 定时扫描和后台任务 | [Celery 配置](../../backend/app/tasks/celery_app.py) |
| 运行配置 | 本地/生产 Compose、前端 Nginx、外部 Nginx | [部署说明](./deployment.md) |

## 不在当前架构承诺内

独立 DoctorAgent、KnowledgeAgent、MCP、GraphRAG 和 Android 客户端属于历史提案或后续候选。数据库中存在 care plan、reminder 或 Celery 定时任务，也不等于已形成完整、可靠的随访送达闭环。需求和差距以 [PRD](../product/PRD.md) 为准。
