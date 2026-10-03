# 本地与生产配置

> 本页说明仓库内的 Compose 和 Nginx 配置，不声明生产环境当前运行状态。静态核对日期：**2026-09-29**。

## 本地 Docker Compose

本地栈由根目录 docker-compose.yml 定义，默认启动 PostgreSQL、Redis、backend、Celery worker、Celery beat 和 frontend。SearXNG 位于 `external-search` profile，默认不启动；管理员将外部搜索地址设为 `http://searxng:8080` 时，只有启动该服务后才能使用外部检索。

| 服务 | 主机绑定 | 容器端口/作用 |
|---|---|---|
| PostgreSQL | 127.0.0.1:5433 | 5432 |
| Redis | 127.0.0.1:16379 | 6379 |
| backend | 127.0.0.1:8000 | 8000 |
| frontend | 127.0.0.1:3000 | 80 |
| Celery worker / beat | 无主机端口 | 后台任务进程 |
| SearXNG（按需） | 无主机端口 | 8080，仅供 Compose 网络内的 backend 访问 |

PostgreSQL 与 Redis 使用命名卷。backend 将 app 目录以只读方式挂载；frontend 使用镜像内构建产物。

启动前复制 .env.example 为 .env 并填写必要配置：

首次启动和带有迁移脚本的代码更新，须先按[根 README 的快速启动步骤](../../README.md)初始化或升级数据库，再启动应用。以下命令用于已经完成迁移的本地栈；重启容器不会自动执行 Alembic 迁移，`/health` 返回正常也不表示表结构已与代码同步。

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

需要外部检索时，先在未提交的 `.env` 中设置随机 `SEARXNG_SECRET`，确认现有 Redis 正在运行，再执行以下命令。它只启动一个 SearXNG 服务容器，复用现有 Redis 的 DB 3，不创建第二套数据库或缓存，也不向宿主机开放 SearXNG 端口。

~~~sh
docker compose --profile external-search config -q
docker compose --profile external-search up -d --no-deps searxng
docker compose --profile external-search ps searxng
~~~

服务启动后，从 backend 容器检查 `searxng` 是否可解析，并用管理员的外部搜索健康检查确认 `/search?format=json` 返回正常。若未启动此 profile，应在管理员设置中关闭外部搜索，避免把缺少服务误判为通用 DNS 故障。

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
