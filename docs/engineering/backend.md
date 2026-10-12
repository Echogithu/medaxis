# 后端参考

> 当前工作区静态源码索引，核对日期：**2026-10-06**。本轮仅核对文档与代码，未启动后端、迁移或验证外部依赖。

## 技术与入口

- Python 3.12+，FastAPI、SQLAlchemy Async、Pydantic、Alembic；依赖定义见 [pyproject.toml](../../backend/pyproject.toml)。
- 应用入口为 [app.main:app](../../backend/app/main.py)，v1 路由聚合见 [api/v1/__init__.py](../../backend/app/api/v1/__init__.py)。
- v1 前缀为 /api/v1。根级 GET /health、GET /ready 与 v1 的 GET /api/v1/health/ 是不同检查入口。
- development 环境开放 OpenAPI /docs 和 /redoc；其他环境关闭。专用演示模式额外拒绝 /docs、/redoc 与 /openapi.json。
- 数据库连接与 Redis 客户端见 [db/session.py](../../backend/app/db/session.py) 和 [db/redis_client.py](../../backend/app/db/redis_client.py)。

## API 分组

| 前缀或路径 | 主要能力 | 说明 |
|---|---|---|
| /api/v1/auth | 注册、登录、访客会话、身份验证、角色和访客数据迁移 | 普通模式能力；专用演示模式关闭访客/公开注册等入口 |
| /api/v1/agents | 问诊、诊断、计划、监测、咨询、SSE、会话与诊后追问 | 访问规则因端点而异 |
| /api/v1/medical-cases | 病例和病例文档管理 | 旧 PRD 的字段漂移为历史问题；当前权限和行为以端点为准 |
| /api/v1/doctor | 医生统计、病例列表和详情、占位计划接口 | 计划指令返回 501；部分统计固定为 0、风险等级固定为 medium，页面仍有演示回退 |
| /api/v1/patient | 档案、病例恢复、就医准备、自报反馈、手动计划、提醒与 check-in | 还挂载诊后 AI 安排和独立报告中心；患者确认不等于医生确认 |
| /api/v1/admin | 用户、医生审核、模型供应商、系统配置、知识库和审计 | router 层有管理员角色守卫 |
| /api/v1/documents | 聊天医学文件异步解析、查询结果和删除 | 原件与任务状态落库；读取/删除检查上传账号或有效访客归属 |
| /api/v1/patient/reports | 独立归档、取字、逐次同意整理、核对历史、病例引用和回收站 | 新模块需对应迁移；代码存在不等于当前演示库已就绪 |
| /api/v1/upload | 病例附件上传及文件元信息 | 与医学报告解析是另一套入口 |
| /api/v1/rag | 知识文档写入、查询和搜索 | embedding 以 JSONB 保存，代码执行相似度计算 |
| /api/v1/llm | 普通对话、流式对话和健康检查 | 外部模型配置决定是否可用 |

重要路径：

- POST /api/v1/agents/route/stream：问诊 SSE 入口；主诉与病史在 JSON body，凭证和 `Idempotency-Key` 在请求头。
- POST /api/v1/agents/route/stream/continue：提交问诊卡答案并继续问诊；答案在 JSON body，`session_id` / `question_id` 为 query 参数。
- POST /api/v1/agents/sessions/{session_id}/chat：诊断后独立对话，返回 SSE。
- 三条患者 SSE 路由在通用身份解析前拒绝 URL 凭证和患者文本；续答仅保留不透明 `session_id` / `question_id` query 参数。其他兼容路由仍可能使用旧 query-token 解析。
- POST /api/v1/documents/upload：上传原件并创建解析任务，结果由 /api/v1/documents/{file_id}/result 轮询。
- POST /api/v1/upload/upload：病例附件落盘，不是上一个异步解析接口。

路由源码：[agents.py](../../backend/app/api/v1/agents.py)、[documents.py](../../backend/app/api/v1/documents.py)、[upload.py](../../backend/app/api/v1/upload.py)。

独立报告入口见 [patient_reports.py](../../backend/app/api/v1/patient_reports.py) 及其挂载的 workflow/review/links/lifecycle 路由。该入口先归档、在平台内取字，再按本次预览与同意发送文字；旧聊天解析仍可能外发原图/文件，不能合称“所有原件不外发”。

## 核心服务

- [Agent 服务](../../backend/app/services/agents.py)实现诊断、规划、监测、MasterAgent 和 AgentOrchestrator 等服务结构。
- [Interview 编排器](../../backend/app/services/orchestrator.py)负责 Track1 病史采集、Track2 搜索增强和下一步问诊决策。
- [意图分类](../../backend/app/services/intent.py)识别问诊、规划、监测、咨询、研究及一般对话等用途；超时或低置信度时采用保守回退策略。
- [LLM 服务](../../backend/app/services/llm.py)按数据库配置选择供应商与模型。代码支持多 provider 配置，但本轮未发现跨 provider 故障时自动切换；同一 provider 的重试不等于故障转移。
- [RAG 服务](../../backend/app/services/rag.py)独立执行关键词与同模型向量召回，合并候选后可选 reranker；当前向量路径对 JSONB embedding 做应用层流式精确扫描。来源工具可补充锚点前后文，并在引用排序时核对问题要点覆盖；模型判断失败回退既有来源策略。
- [外部搜索](../../backend/app/services/external_search.py)通过 SearXNG 获取外部搜索结果；是否可用取决于服务部署和配置，普通本地 Compose 栈不启动 SearXNG。

## 数据与异步任务边界

- 异步 PostgreSQL 会话与连接池由 SQLAlchemy 管理；Alembic 迁移位于 backend/app/db/migrations/versions。
- Celery worker 与 beat 使用 Redis broker/result backend；beat 中配置了定时清理及监测事件扫描任务。
- 聊天解析 API 使用 DocumentParseTask 保存原件字节、归属、状态与结果；Celery 按 file_id 读取持久任务，已完成/失败任务不重复处理。迁移与任务配置是运行前提；持久化并不证明中断恢复或多进程可靠性已验收。
- 独立报告原件、处理任务、人工版本、引用及提交记录另行存储，模型见 [patient_report.py](../../backend/app/models/patient_report.py)。文件限制与外发边界应按入口区分。

## 权限与审查边界

当前源码与旧 PRD 需区分：

- 医学文档轮询/删除已检查身份和归属；医生病例接口已有医生角色与分配关系检查。旧缺陷不再作为当前问题。
- 医生角色检查尚不等于认证审核门禁：`_require_doctor` 未检查 `is_verified`；医生完整协作及权限矩阵仍待验收。
- Redis 不可用时，部分 token blacklist 检查走 fail-open 路径。
- 公开注册已拒绝创建管理员；演示模式进一步关闭注册及访客，仅允许专用患者身份。额度、输出限制和恢复前置条件见[面试演示说明](../INTERVIEW_DEMO.md)。

这些是代码审查结论，不是生产攻击测试。权限矩阵和真实 API 验收尚未在本次文档工作中执行。

## 本地运行与测试

从仓库根目录开始：

~~~sh
cd backend
pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
~~~

运行前需准备 PostgreSQL、Redis 及 backend 可读的环境配置；本机连接须使用宿主机映射端口，不能直接使用 Compose 内服务名。依赖安装、迁移与服务启动均未由本轮执行。

数据库测试的 fixture 会建表和删表。先创建与业务/演示库分离的 `medaxis_test_*` PostgreSQL 库，替换下列占位用户/密码，再执行；不能用业务库代替：

~~~powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://TEST_USER:TEST_PASSWORD@127.0.0.1:5433/medaxis_test_local'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
$env:ASYNC_DATABASE_URL=$env:TEST_DATABASE_URL
$env:MEDAXIS_ALLOW_DESTRUCTIVE_TEST_DB='1'
python -m pytest -q
~~~

完整约束见[测试安全护栏](../../backend/tests/database_safety.py)。纯单元测试与数据库测试分开执行；历史测试数量按日期与范围阅读，不能作为本次复跑结果。
