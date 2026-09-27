# 医枢 MedAxis

> 面向患者、医生与运营人员的 AI 辅助问诊和医疗协作平台

MedAxis 将多轮问诊、检验报告解析、医学资料检索、诊后追问及患者管理功能放在同一套 Web 应用中。AI 输出用于信息整理与辅助参考，不构成正式诊断、处方或急救服务。出现紧急、快速恶化或危及生命的症状时，请及时联系当地急救机构或合格医疗专业人员。

## 当前状态

以下是截至 **2026-09-24** 对源码和配置的静态核对，不代表服务已在当前机器启动，也不代表医疗质量或生产环境已验收。

| 范围 | 当前代码状态 | 边界 |
|---|---|---|
| AI 问诊与结构化报告 | 有问诊、续答、意图分类和报告生成代码 | 真实模型表现、临床安全性及端到端流程未在本轮验证 |
| 报告上传与解析 | 有上传、解析和结果轮询入口 | 解析任务状态保存在后端进程内存，不能视为可靠的持久任务队列 |
| 患者档案、随访和提醒 | 有相关 API 和页面 | 数据字段、任务状态与发送确认尚未形成完整、已验收的闭环 |
| 医生工作台 | 有病例列表、统计和详情入口 | 部分页面仍含演示数据或模拟成功路径，不能当作完整医生协作流程 |
| 管理后台 | 有用户、医生、模型配置、知识库和运营管理模块 | 整体可用性、类型检查和端到端流程仍需单独验证 |
| MCP、GraphRAG、Android | 属于历史提案或后续候选 | 当前不作为已交付能力 |
| 生产部署 | 仓库包含生产 Compose、Nginx 和部署脚本 | 配置文件不证明线上环境正在运行或已通过验收 |

详细范围和代码审查结论见[产品需求与实现差距](./docs/product/PRD.md)及[待处理问题](./docs/product/todos.md)。

## 技术组成

| 层 | 当前实现 |
|---|---|
| 后端 API | Python 3.12、FastAPI、SQLAlchemy Async、Pydantic |
| 数据与任务 | PostgreSQL、Alembic、Redis、Celery |
| 前端 | React 19、TypeScript 6、Vite 8、MUI 9 |
| AI 集成 | OpenAI 兼容模型供应商、医学资料检索、按配置接入 SearXNG 外部搜索 |
| 本地运行 | Docker Compose |

RAG 当前使用 PostgreSQL 关键词召回、JSONB 中的 embedding 相似度计算及可选 reranker。Compose 使用 pgvector PostgreSQL 镜像，但当前模型将 embedding 存入 JSONB；不要据此描述为已使用 pgvector 向量列。普通本地 Compose 栈不启动 SearXNG，外部搜索是否可用取决于服务部署和配置。详见[数据库说明](./docs/engineering/database.md)。

## 本地快速启动

### 环境要求

- Docker Engine 或 Docker Desktop
- Docker Compose v2
- 若分别启动前后端：Python 3.12+、Node.js 22+

### 1. 配置环境

克隆仓库后，在项目根目录复制环境模板并编辑本地配置：

~~~powershell
Copy-Item .env.example .env
~~~

macOS/Linux 可使用：

~~~sh
cp .env.example .env
~~~

按模板填写必需配置，尤其要设置仅在本机保存的强随机密钥及模型服务配置。不要把真实密钥、患者数据或上传文件提交到仓库。

### 2. 启动本地 Compose 栈

~~~sh
docker compose up -d --build
docker compose ps
~~~

本地入口：

- 前端：<http://localhost:3000>
- API：<http://localhost:8000>
- 后端健康检查：<http://localhost:8000/health>
- 后端就绪检查：<http://localhost:8000/ready>
- OpenAPI 文档：<http://localhost:8000/docs>（仅 development 环境开放）

本地 Compose 公开绑定在回环地址的端口为：PostgreSQL 5433、Redis 16379、后端 8000、前端 3000。数据库和 Redis 数据保存在 Compose 命名卷中。

~~~sh
docker compose logs -f backend
docker compose logs -f frontend
docker compose down
~~~

down 会停止并移除容器，命名数据卷仍保留。

### 分别启动前后端

如需使用本机热重载，先启动 Compose 中的数据库与 Redis：

~~~sh
docker compose up -d postgres redis
~~~

后端依赖数据库连接地址与本地环境配置；确认连接地址使用 Compose 映射端口后再运行迁移和服务：

~~~sh
cd backend
python -m venv .venv
pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
~~~

Windows PowerShell 中可激活相应虚拟环境后再运行上述命令。

前端开发服务器默认监听 3000，并将 /api 代理到 http://localhost:8000：

~~~sh
cd frontend
npm ci
npm run dev
~~~

若同时运行 Compose 前端，需先停止其中一个或为 Vite 指定其他端口。

## 验证入口

以下是仓库声明的本地验证命令。本次工作只改写文档，没有运行应用测试、构建或部署。

~~~sh
cd frontend
npm test
npm run build
npm run lint
~~~

~~~sh
cd backend
pytest -q
~~~

~~~sh
python evals/patient-smoke/run_eval.py --check
docker compose -f docker-compose.yml config -q
docker compose -f docker-compose.prod.yml config -q
~~~

前端浏览器回归脚本使用模拟 API/SSE，依赖 Playwright 和 Edge；脚本默认使用 127.0.0.1:3001，与 Vite 默认端口不同。完整步骤见[前端说明](./docs/engineering/frontend.md)。

## 项目结构

~~~text
medaxis/
├── backend/
│   ├── app/api/v1/       # REST 与 SSE API
│   ├── app/core/         # 配置、认证及基础设施
│   ├── app/db/           # 数据库会话与 Alembic 迁移
│   ├── app/models/       # SQLAlchemy 模型
│   ├── app/schemas/      # Pydantic Schema
│   ├── app/services/     # Agent、LLM、RAG、邮件等服务
│   ├── app/tasks/        # Celery Worker / Beat
│   └── tests/            # 后端测试
├── frontend/
│   ├── src/api/          # API 客户端与 SSE
│   ├── src/auth/         # 登录、注册与身份状态
│   ├── src/doctor/       # 医生端
│   ├── src/admin/        # 管理后台
│   ├── src/patient/      # 患者健康管理
│   ├── src/state/        # 会话历史与状态
│   └── tests/            # 前端测试
├── docs/                 # 项目说明、审查型 PRD 与历史提案
├── evals/patient-smoke/  # 合成冒烟题集 SM-01–SM-10（DEFINED_NOT_RUN）
├── nginx/                # 外部反向代理配置
├── searxng/              # SearXNG 配置
├── scripts/              # 部署与迁移脚本
├── docker-compose.yml    # 本地开发栈
└── docker-compose.prod.yml
~~~

## 文档

- [文档索引](./docs/README.md)
- [系统架构](./docs/engineering/architecture.md)
- [后端参考](./docs/engineering/backend.md)
- [前端参考](./docs/engineering/frontend.md)
- [数据库说明](./docs/engineering/database.md)
- [本地与生产配置](./docs/engineering/deployment.md)
- [待处理问题摘要](./docs/product/todos.md)
- [产品需求与实现差距审查（REVIEW）](./docs/product/PRD.md)
- [患者侧聚焦 PRD](./docs/product/PORTFOLIO_PRD.md)
- [患者侧合成冒烟题集](./evals/patient-smoke/README.md)
- [历史架构提案](./docs/archive/PROPOSAL.md)

docs/product/PRD.md 当前为待评审的需求与实现差距文档，不代表开发授权。历史提案只描述设计方向，不能替代当前源码说明。

## 开发边界

- 医疗相关输出必须明确 AI 辅助属性、证据边界和风险提示。
- 不将 AI 建议表述为确诊、处方或医生已确认意见。
- API、Schema、数据库或页面契约变更时，应同步核对其调用方和对应文档。
- 处理真实数据或部署环境前，须另行制定权限、备份、验证和回滚方案。
