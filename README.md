# Project Template

## 可观测性（OpenTelemetry）

FastAPI 请求和 PostgreSQL 调用通过官方 OTel instrumentation 采集；Redis 使用 `fastapi-redis-sdk` 自带的观测能力。Traces、metrics、logs 共用服务标识，通过 OTLP/HTTP 发给 Alloy，分别转发至 Tempo、Prometheus、Loki。本机和 Docker 使用同一日志推送通路，终端和 `docker logs` 仍保留可读文本；Docker 的重复采集需按[接入说明](deploy/observability/README.md#docker-避免重复采集)排除。

默认关闭 OTel。启用时在本地 `api/.env.local` 或服务器部署 `.env` 中配置以下变量；地址为占位值：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=project-template-api
OTEL_DEPLOYMENT_ENVIRONMENT=test
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal.example.com:4318
OTEL_LOGS_ENABLED=true
OTEL_LOGS_LEVEL=INFO
REDIS_OTEL_ENABLED=true
REDIS_OTEL_REDIS_ENABLED=true
```

同样支持 `Settings.otel` / TOML `[otel]`，环境变量优先于配置文件。`OTEL_SDK_DISABLED=true` 可总关闭，`OTEL_FASTAPI_ENABLED`、`OTEL_POSTGRES_ENABLED` 和两个 Redis SDK 开关可分别控制。配置修改后重启 API；生产须配置自身可达的 collector。完整配置、采样、信号范围和查询步骤见 [OTel 接入与验证](deploy/observability/README.md)。

## 运行与部署总览

项目支持本地开发、测试服务器、生产服务器三种使用方式。完成各自的首次准备后，可使用下表入口启动或发布；部署文件已经提供，不代表新服务器和 GitHub 已自动配置完成。

| 场景 | 日常入口 | 首次准备 | 默认访问方式 |
| --- | --- | --- | --- |
| [本地开发](#本地开发) | `just run`，前后端热更新 | pnpm、uv、just、项目依赖、可用的 Postgres/Redis 与 API 配置 | 前端 `http://localhost:5173`，API `http://localhost:8000` |
| [测试服务器](#测试服务器) | 推送 `main`，或 Actions 手动选择 `test` | Docker Compose、部署配置、SSH 密钥、可达测试机的 runner | 服务器 `127.0.0.1:18080`，通过 SSH 隧道访问 |
| [生产服务器](#生产服务器) | 推送 `v*` 标签，或 Actions 手动选择 `production` | Docker Compose、部署配置、SSH 密钥、GitHub Environment | 服务器 `127.0.0.1:18080`，通过 SSH 隧道访问 |

以下命令默认在仓库根目录执行。文档中的 `deploy@test.example.com`、`deploy@prod.example.com` 和 `ghcr.io/your-org/your-repository` 都是占位值，需要替换。真实地址、账户、SSH 别名和密钥保存在本地配置、服务器配置或 GitHub 设置中，不写入 README。

## 本地开发

### 首次准备

安装 pnpm、uv 和 just；Python 版本满足 `api/pyproject.toml` 的 `>=3.14`，Node/pnpm 使用 `package.json` 中指定的版本。安装依赖并初始化开发端口配置：

```bash
pnpm install --frozen-lockfile
uv sync --locked --package api
test -f .env || cp .env.example .env
```

准备可连接的 PostgreSQL 18 与 Redis，并事先创建应用数据库和账户。`just run` 不会启动数据库、Redis 或执行迁移。后端从 `api/` 读取配置，可在被 Git 忽略的 `api/config.local.toml` 中填写以下最小配置；已有配置时合并所需字段，替换示例账户和密码：

```toml
repo_type = "postgres"

[app]
env = "dev"
debug = true

[postgres]
host = "127.0.0.1"
port = 5432
username = "app"
password = "replace-with-your-local-password"
database = "app"

[redis]
host = "127.0.0.1"
port = 6379
db = 0
password = "replace-with-your-local-password"
```

Redis 未启用认证时使用空密码。也可在 `api/.env` 中设置 `POSTGRES_HOST`、`POSTGRES_USERNAME`、`REDIS_HOST` 等环境变量，它们优先于 TOML 配置；根目录 `.env` 主要用于开发端口。模型与对象存储配置仅在使用对应业务功能时补充，完整字段见 [API 配置示例](api/config.example.toml)。

首次连接应用数据库或新增迁移后执行：

```bash
uv run --directory api alembic upgrade head
```

### 日常启动

```sh
just run                                  # 同时启动 Vite 和 FastAPI
just run --web-port 6173 --api-port 9036    # 覆盖两端端口，代理随之后端端口变化
just web --port 6173                      # 只启动前端，也支持 -p
just api --port 9036                      # 只启动后端，也支持 -p
WEB_PORT=6173 API_PORT=9036 just run       # 通过环境变量设置端口
```

共享端口写在根目录 `.env`，格式见 [.env.example](.env.example)。优先级为 recipe flags、终端环境变量、`.env`、内置默认值（前端 `5173`、后端 `8000`）。端口被占用会直接报错。`just run` 使用 macOS/Linux 进程组管理：按 Ctrl+C 会关闭本次启动的两个服务；任一服务进程退出时也会清理另一个服务。

浏览器打开前端地址。可通过 `curl --fail http://127.0.0.1:8000/api/health` 检查 API、Postgres 和 Redis；修改端口后同步替换检查地址。前端使用 `/api/...` 相对路径，Vite 将其转发至对应 API 端口；部署环境由 Nginx 代理同一路径，详见 [web 开发与部署](web/README.md#api-代理与部署)。

业务页面现需登录。先执行数据库迁移，再配置 Google OAuth 客户端或启用密码渠道并通过 `api.auth.manage create-user` 创建账号；手机号仅预留扩展，钉钉按需启用。指定服务接口另支持 Header API Key，详见 [用户、认证与请求追踪](api/README.md#api-用户与认证)。本地浏览器入口、`auth.frontend_url` 和 OAuth 回调统一使用 `localhost`，不要与 `127.0.0.1` 混用；自定义端口时同步调整这三处。HTTP 开发需设置 `REDIS_SESSION_COOKIE_HTTPS_ONLY=false`，生产使用 HTTPS。

### 本地整套 Compose 验证（可选）

如果本机已运行 Docker，可以一次启动前端、API、Postgres、Redis 和迁移，无需单独配置外部数据库。该方式运行构建后的镜像，不提供 `just run` 的源码热更新：

```bash
bash deploy/init-env.sh test "$PWD/deploy"
docker compose --env-file deploy/.env up -d --build --wait web
curl --fail http://127.0.0.1:18080/api/health
```

浏览器打开 `http://127.0.0.1:18080`。修改源码后重跑 `up -d --build --wait web`；停止时运行 `docker compose --env-file deploy/.env down`，保留数据卷。这里使用 `deploy/.env`，与根目录开发端口 `.env`、后端 `api/` 配置独立；不要添加 `down -v`，以免删除数据。

## 服务器首次准备（测试与生产共用）

先在本地终端设置各环境的连接目标，以下仅为占位示例：

```bash
export TEST_SSH_TARGET='deploy@test.example.com'
export PRODUCTION_SSH_TARGET='deploy@prod.example.com'
```

两台服务器均需要 Docker Engine、Compose、Bash、tar、flock、curl、openssl，以及部署账户直接运行 Docker 的权限。Ubuntu 首次安装 Docker、可信主机密钥与 runner 的准备步骤见 [部署运维文档](deploy/README.md#首次准备服务器)。然后分别初始化配置：

```bash
ssh "$TEST_SSH_TARGET" 'bash -s -- test' < deploy/init-env.sh
ssh "$PRODUCTION_SSH_TARGET" 'bash -s -- production' < deploy/init-env.sh
```

脚本为各环境生成独立随机密码，配置分别保存在服务器 `$HOME/apps/project-template/test/.env` 和 `$HOME/apps/project-template/production/.env`；重复执行保留现有配置。业务密钥按需写入这些文件，服务器只需拉取镜像，无需安装本项目的 pnpm 或 Python 开发环境。

在 GitHub 创建 `test`、`production` 两个 Environment，各自设置：

| 配置位置 | 必需项 | 可选项 |
| --- | --- | --- |
| Environment Secrets | `SSH_PRIVATE_KEY`、`SSH_KNOWN_HOSTS` | — |
| Environment Variables | `SSH_HOST`、`SSH_USER` | `SSH_PORT`、`DEPLOY_PATH`、`HTTP_BIND`、`HTTP_PORT` |
| Repository Variables | 默认 runner 满足要求时无需设置 | `TEST_DEPLOY_RUNNER`、`PRODUCTION_DEPLOY_RUNNER`（JSON 标签数组） |

`SSH_HOST` 填写 runner 实际可达的地址，不填写本地终端中的 SSH 别名。测试部署默认选择带 `project-template-deploy` 标签的 Linux x64 self-hosted runner，必须能访问测试机；生产部署默认从 GitHub 托管 runner 经 SSH 连接生产机。完整设置见 [runner 配置](deploy/README.md#配置测试环境-runner)和 [Environment 与 SSH 配置](deploy/README.md#配置-github-environments-与-ssh)。工作流文件必须先提交并推送，自动部署才会生效。

## 测试服务器

完成上述准备后，将代码合并到 `main` 并推送即可自动发布：

```bash
git push origin main
```

也可打开 GitHub **Actions → Deploy → Run workflow**，选择 `test`。流程自动构建双架构镜像、发布 GHCR、运行 Compose 集成检查，再通过 SSH 拉取镜像、迁移数据库和更新服务。发布使用不可变镜像 digest。

测试环境默认使用生产构建与 `APP_ENV=prod`，不开启调试；Postgres、Redis 和 API 只在 Compose 网络内通信。默认访问需要在本地保持以下隧道运行：

```bash
ssh -N -L 18080:127.0.0.1:18080 "$TEST_SSH_TARGET"
```

然后访问 `http://127.0.0.1:18080`；另一个终端可执行 `curl --fail http://127.0.0.1:18080/api/health`。

## 生产服务器

确认当前提交是目标发布版本后，创建一个尚未使用的 `v*` 标签并推送；以下版本号仅为示例：

```bash
git tag v0.1.0
git push origin v0.1.0
```

也可在 **Actions → Deploy → Run workflow** 中选择 `production`。发布过程与测试环境相同，使用独立的 Environment 配置、数据库和数据卷，镜像同时支持 x86_64 与 ARM64。

生产默认仅绑定服务器 `127.0.0.1:18080`，无需开放公网业务端口。下面使用本地 `18081`，可与测试环境隧道同时运行：

```bash
ssh -N -L 18081:127.0.0.1:18080 "$PRODUCTION_SSH_TARGET"
```

然后访问 `http://127.0.0.1:18081`，或执行 `curl --fail http://127.0.0.1:18081/api/health`。如果修改了服务器 `HTTP_PORT`，同步调整隧道右侧端口。

服务通过重启策略在 Docker 恢复运行后自动启动，已有数据库与文件保存在持久卷中。发布为原地更新，可能短暂中断；失败不会自动逆转迁移。手动指定镜像发布、日志、备份和回滚见 [部署运维文档](deploy/README.md#发布访问与排查)。

# docs

`docs/` 使用 VitePress 2，目录本身就是文档根目录，Markdown 文件路径直接生成路由。

```shell
pnpm install
pnpm docs:dev      # http://localhost:5174
pnpm docs:build    # 输出到 docs/.vitepress/dist
pnpm docs:preview  # http://localhost:4174
```

站点配置位于 `docs/.vitepress/config.mts`，使用说明见 [快速开始](docs/guide/index.md)。

`docs-mdx/` 保留为独立的 base-ui MDX 文档站，原命令改为 `docs-mdx:*`：

```shell
pnpm docs-mdx:dev
pnpm docs-mdx:build
pnpm docs-mdx:start
pnpm docs-mdx:check-types
pnpm docs-mdx:test
pnpm docs-mdx:link-check
```

## Notes

- Use uv workspace globally, but don't use workspace when deploy

## web

### start

```shell
# create directory
mkdir "web" && cd "web"

#
pnpm init

pnpm create vite@latest . --template react-ts

#
pnpm add -Dw oxlint oxfmt typescript
```
