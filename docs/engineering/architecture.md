# 系统架构

> 当前实现视图，静态核对日期：**2026-09-24**。此图展示源码中的主要责任边界，不代表所有外部依赖已运行。

## 系统组成

~~~mermaid
flowchart TD
  User[患者、医生或管理员] --> Web[React Web 应用]
  Web --> API[FastAPI API 与 SSE]
  API --> Auth[身份与权限依赖]
  API --> Agents[问诊与 Agent 服务]
  API --> Patient[患者、病例与管理服务]
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
  Agent->>Search: 按流程检索资料
  Search-->>Agent: 返回可用检索结果
  Agent->>Model: 生成问题或结构化结果
  Model-->>Agent: 返回模型输出
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
- 报告解析接口与病例附件上传是两条不同路径。解析任务目前由进程内状态表记录，进程重启或跨 worker 查询的可靠性有限；接口见 [documents API](../../backend/app/api/v1/documents.py)。
- PostgreSQL 保存账户、病例、会话、知识库及管理数据；Redis 也用于 token blacklist/cache、Celery broker/result backend。表与存储边界见[数据库说明](./database.md)。
- 浏览器端历史使用 localStorage，不等同于跨设备同步的云端历史；见[前端说明](./frontend.md)。

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
