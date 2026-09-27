# 后端参考

> 静态源码索引，核对日期：**2026-09-24**。端点和服务代码存在不代表本轮已启动后端或验证外部依赖。

## 技术与入口

- Python 3.12+，FastAPI、SQLAlchemy Async、Pydantic、Alembic；依赖定义见 [pyproject.toml](../../backend/pyproject.toml)。
- 应用入口为 [app.main:app](../../backend/app/main.py)，v1 路由聚合见 [api/v1/__init__.py](../../backend/app/api/v1/__init__.py)。
- v1 前缀为 /api/v1。根级 GET /health、GET /ready 与 v1 的 GET /api/v1/health/ 是不同检查入口。
- development 环境开放 OpenAPI /docs 和 /redoc；其他环境关闭。
- 数据库连接与 Redis 客户端见 [db/session.py](../../backend/app/db/session.py) 和 [db/redis_client.py](../../backend/app/db/redis_client.py)。

## API 分组

| 前缀或路径 | 主要能力 | 说明 |
|---|---|---|
| /api/v1/auth | 注册、登录、访客会话、身份验证、角色和访客数据迁移 | 不把未核实的 refresh token 能力写入 API 清单 |
| /api/v1/agents | 问诊、诊断、计划、监测、咨询、SSE、会话与诊后追问 | 访问规则因端点而异 |
| /api/v1/medical-cases | 病例和病例文档管理 | 当前 API 与模型字段仍有差异，参见 PRD 风险项 |
| /api/v1/doctor | 医生统计、病例列表和详情、计划 | 部分响应/页面数据仍需端到端核对 |
| /api/v1/patient | 健康档案、病例、计划、提醒、check-in | 存在前后端数据契约待核对项 |
| /api/v1/admin | 用户、医生审核、模型供应商、系统配置、知识库和审计 | router 层有管理员角色守卫 |
| /api/v1/documents | 医学文件异步解析、查询结果和删除 | 解析任务状态存在进程内存中 |
| /api/v1/upload | 病例附件上传及文件元信息 | 与医学报告解析是另一套入口 |
| /api/v1/rag | 知识文档写入、查询和搜索 | embedding 以 JSONB 保存，代码执行相似度计算 |
| /api/v1/llm | 普通对话、流式对话和健康检查 | 外部模型配置决定是否可用 |

重要路径：

- GET /api/v1/agents/route/stream：问诊 SSE 入口。
- POST /api/v1/agents/route/stream/continue：提交问诊卡答案并继续问诊。
- POST /api/v1/agents/sessions/{session_id}/chat：诊断后独立对话，返回 SSE。
- POST /api/v1/documents/upload：上传并开始解析，结果由 /api/v1/documents/{task_id}/result 轮询。
- POST /api/v1/upload/upload：病例附件落盘，不是上一个异步解析接口。

路由源码：[agents.py](../../backend/app/api/v1/agents.py)、[documents.py](../../backend/app/api/v1/documents.py)、[upload.py](../../backend/app/api/v1/upload.py)。

## 核心服务

- [Agent 服务](../../backend/app/services/agents.py)实现诊断、规划、监测、MasterAgent 和 AgentOrchestrator 等服务结构。
- [Interview 编排器](../../backend/app/services/orchestrator.py)负责 Track1 病史采集、Track2 搜索增强和下一步问诊决策。
- [意图分类](../../backend/app/services/intent.py)识别问诊、规划、监测、咨询、研究及一般对话等用途；超时或低置信度时采用保守回退策略。
- [LLM 服务](../../backend/app/services/llm.py)按数据库配置选择供应商与模型。代码支持多 provider 配置，但本轮未发现跨 provider 故障时自动切换；同一 provider 的重试不等于故障转移。
- [RAG 服务](../../backend/app/services/rag.py)先做关键词候选检索，再按 JSONB embedding 计算相似度，并可选 reranker。
- [外部搜索](../../backend/app/services/external_search.py)通过 SearXNG 获取外部搜索结果；是否可用取决于服务部署和配置，普通本地 Compose 栈不启动 SearXNG。

## 数据与异步任务边界

- 异步 PostgreSQL 会话与连接池由 SQLAlchemy 管理；Alembic 迁移位于 backend/app/db/migrations/versions。
- Celery worker 与 beat 使用 Redis broker/result backend；beat 中配置了定时清理及监测事件扫描任务。
- 医学文档解析 API 当前将 task 状态保存在模块级 _parse_tasks 内存字典中。重启会丢失状态，多个 worker 之间也没有共享状态保证。
- 文件上传限制、格式支持和路径策略以具体 endpoint 与文档路由实现为准；不要把两个上传入口描述成同一套持久化流程。

## 权限与审查边界

当前静态审查至少发现以下需要在修复前纳入风险说明的问题：

- 医学文档解析结果的轮询/删除入口缺少身份依赖与所有权检查。
- 医生病例详情入口的角色和病例归属校验需要补齐。
- Redis 不可用时，部分 token blacklist 检查走 fail-open 路径。
- 公开注册角色、管理操作和演示数据的边界见 [PRD 风险审查](../product/PRD.md)。

这些是代码审查结论，不是生产攻击测试。权限矩阵和真实 API 验收尚未在本次文档工作中执行。

## 本地运行与测试

从仓库根目录开始：

~~~sh
cd backend
pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
pytest -q
~~~

运行前需准备 PostgreSQL、Redis 及 backend 可读的环境配置。依赖安装、数据库迁移和服务启动均未由本轮执行。
