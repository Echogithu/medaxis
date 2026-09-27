# 本地与生产配置

> 本页说明仓库内的 Compose 和 Nginx 配置，不声明生产环境当前运行状态。静态核对日期：**2026-09-24**。

## 本地 Docker Compose

本地栈由根目录 docker-compose.yml 定义，包含 PostgreSQL、Redis、backend、Celery worker、Celery beat 和 frontend；不包含 SearXNG，因此该栈本身不能保证外部搜索可用。

| 服务 | 主机绑定 | 容器端口/作用 |
|---|---|---|
| PostgreSQL | 127.0.0.1:5433 | 5432 |
| Redis | 127.0.0.1:16379 | 6379 |
| backend | 127.0.0.1:8000 | 8000 |
| frontend | 127.0.0.1:3000 | 80 |
| Celery worker / beat | 无主机端口 | 后台任务进程 |

PostgreSQL 与 Redis 使用命名卷。backend 将 app 目录以只读方式挂载；frontend 使用镜像内构建产物。

启动前复制 .env.example 为 .env 并填写必要配置：

~~~sh
docker compose config -q
docker compose up -d --build
docker compose ps
~~~

停止服务但保留命名卷：

~~~sh
docker compose down
~~~

运行日志可使用 docker compose logs -f backend 或 docker compose logs -f frontend。健康检查入口为 http://localhost:8000/health。

## 独立开发服务器

如需热重载，可只通过 Compose 启动 PostgreSQL 和 Redis，再从本机启动 backend 与 Vite。后端数据库地址必须指向宿主机映射端口；容器内服务名 postgres/redis 只适用于 Compose 网络。完整步骤见[根 README](../../README.md)。

Vite 默认使用 3000，正好与 Compose 前端映射冲突；不要在不调整端口的情况下同时启动两者。

## 生产配置文件

docker-compose.prod.yml 定义八个容器服务：PostgreSQL、Redis、backend、Celery worker、Celery beat、frontend、Valkey 和 SearXNG。PostgreSQL/Redis/Valkey 不直接绑定宿主机端口；backend 与 frontend 仅绑定 127.0.0.1。外部 Nginx 配置位于 nginx/nginx.conf，处理公网入口、API 代理、SSE 和静态前端转发。

以上仅能说明仓库中存在这些配置，不能证明它们已在目标主机部署、健康或已完成数据迁移。生产域名、主机地址和 SSH 命令不在本页维护。

## 部署与迁移脚本边界

- scripts/deploy.sh 会构建/重建生产 Compose 服务，等待后端健康检查，并执行 Alembic 迁移。
- scripts/migrate-to-medaxis.sh 涉及旧数据备份、卷/上传文件迁移、停旧容器和切换服务；脚本有显式审批与 dry-run 开关。
- 这些脚本会影响运行服务或数据，不能当作普通只读检查。运行前必须重新检查脚本、目标环境、备份完整性、恢复步骤和维护窗口。本轮没有执行它们。

生产配置语法可在依赖 Docker Compose 的环境中静态检查：

~~~sh
docker compose -f docker-compose.prod.yml config -q
~~~

配置解析成功仅说明 Compose 文件可解析，不代表镜像构建成功、迁移安全或服务可用。
