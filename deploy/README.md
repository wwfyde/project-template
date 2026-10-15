# Docker Compose 与 GitHub Actions 部署

部署包含 Nginx 前端、FastAPI、PostgreSQL、Redis 和一次性 Alembic 迁移服务。GitHub Actions 构建 `linux/amd64`、`linux/arm64` 镜像，发布至 `ghcr.io/<owner>/<repository>/{api,web}`，通过 SSH 在服务器拉取镜像并更新 Compose。镜像路径由当前 GitHub 仓库自动生成并转换为小写。

首次启用需要完成下文的服务器初始化、GitHub 环境、部署密钥和 runner 配置，并将工作流推送到仓库。

本地开发、测试服务器和生产服务器的快速入口见[根 README](../README.md)。本文中的域名、账户和镜像路径均为占位示例；将真实连接信息保存在本地 shell 或 GitHub 对应环境的配置中，不要提交到仓库。

## 环境与发布规则

| 环境 | 部署通路 | 初始化前提 | 自动发布触发 |
| --- | --- | --- | --- |
| 测试（`test`） | 能访问测试服务器 SSH 的 self-hosted runner | Docker、Compose、独立 `.env`、runner 和 GitHub 环境配置就绪 | 推送 `main` |
| 生产（`production`） | 默认使用 GitHub 托管 runner 经 SSH 部署 | Docker、Compose、独立 `.env` 和 GitHub 环境配置就绪 | 推送 `v*` 标签 |

Actions → Deploy → Run workflow 可以选择 `test` 或 `production`，发布所选 Git ref。自动发布按环境串行执行，不会主动取消正在运行的迁移。PR 的构建和验证只在 GitHub 托管 runner 运行；测试环境的部署步骤需要能连接测试机的 self-hosted runner。

生产应用端口按未开放处理，默认仅绑定 `127.0.0.1:18080`。外部验证使用 SSH 隧道，部署脚本通过 SSH 在服务器本机检查 HTTP，不依赖公网应用端口。

## 服务与持久化

| 服务 | 用途 | 持久化 |
| --- | --- | --- |
| `postgres` | PostgreSQL 18；现有迁移使用 `uuidv7()` | `postgres-data` → `/var/lib/postgresql` |
| `redis` | Redis 8.2，密码认证、AOF | `redis-data` → `/data` |
| `migrate` | 每次部署执行 `alembic upgrade head` | 使用同一个 Postgres |
| `api` | FastAPI，明确设置 `REPO_TYPE=postgres` | `api-data` → `/app/data` |
| `web` | Nginx 静态文件与 `/api/` 代理 | 无 |

Postgres、Redis 和 API 不发布宿主机端口。测试和生产的初始化配置都使用 `APP_ENV=prod`，Compose 强制 `APP_DEBUG=false`；环境名称 `test` 不代表开启调试。实际卷名带有 `COMPOSE_PROJECT_NAME` 前缀，已有数据后应保留该名称和数据库密码。

数据库、Redis 密码及可选业务配置只保存于服务器的 `.env`，不会打入镜像。镜像使用 `sha-<commit>` 标签便于查找，真正部署使用不可变的 `@sha256:...` digest。

## 首次准备服务器

以下命令在仓库根目录执行。先在当前本地 shell 设置连接目标，替换占位域名和部署账户，不要原样执行，也不要将实际值写进文档：

```bash
export TEST_SSH_TARGET='deploy@test.example.com'
export PRODUCTION_SSH_TARGET='deploy@prod.example.com'
```

这两个变量仅供本地命令使用；GitHub Actions 使用后文配置的 Environment Variables 和 Secrets，不会读取本地 shell 或个人 SSH 别名。先确认两台服务器的状态：

```bash
ssh "$TEST_SSH_TARGET" 'uname -m; docker info >/dev/null && docker compose version'
ssh "$PRODUCTION_SSH_TARGET" 'uname -m; docker info >/dev/null && docker compose version'
```

需要初始化 Docker 的 Ubuntu 服务器可运行，下面以生产环境为例；测试环境将连接目标换成 `"$TEST_SSH_TARGET"`：

```bash
ssh "$PRODUCTION_SSH_TARGET" 'bash -s' < deploy/install-docker-ubuntu.sh
ssh "$PRODUCTION_SSH_TARGET" 'docker info >/dev/null && docker compose version'
```

脚本使用 Docker 官方 apt 源，安装 Engine、Compose 和 Buildx，并将调用用户加入 `docker` 组；需要 root 或免密码 sudo，组变更需重新连接 SSH 后生效。已有 Docker 时只做检查；遇到冲突运行时、定制软件源或需要升级已有包会停止，由管理员处理，不会自动卸载已有运行时。安装依据见 [Docker Ubuntu 文档](https://docs.docker.com/engine/install/ubuntu/)。

部署账户还需要能执行 `bash`、`tar`、`flock`、`curl`、`openssl`，并有目标目录写权限和无 sudo 的 Docker 访问权限。服务器需要访问镜像仓库，测试 runner 需要访问 GitHub 与测试机的 SSH 端口。

在两个环境生成独立配置：

```bash
ssh "$TEST_SSH_TARGET" 'bash -s -- test' < deploy/init-env.sh
ssh "$PRODUCTION_SSH_TARGET" 'bash -s -- production' < deploy/init-env.sh
```

默认目录分别为远端账户的 `$HOME/apps/project-template/test` 和 `$HOME/apps/project-template/production`。指定路径时使用不含空格的绝对路径：

```bash
ssh "$PRODUCTION_SSH_TARGET" 'bash -s -- production /srv/project-template/production' < deploy/init-env.sh
```

`init-env.sh` 创建权限受限的 `.env` 和随机密码；再次执行会保留现有文件。自定义目录需同步设置 GitHub Environment 的 `DEPLOY_PATH`。

可在服务器 `.env` 中按需增加模型与对象存储配置；这些配置不是启动或健康检查的前提：

```dotenv
PROVIDERS='{"openai":{"base_url":"https://api.openai.com/v1","api_key":"实际密钥","model":"实际模型ID"}}'
OSS='{"bucket_name":"实际bucket","region":"实际region","access_key_id":"实际ID","access_key_secret":"实际密钥"}'
```

不要提交该文件。修改配置后重新发布，使 API 容器读取新值。现有 Postgres 数据卷的密码轮换需要同时修改数据库账户密码，不能只改 `.env`。

## 配置测试环境 runner

在仓库 **Settings → Actions → Runners → New self-hosted runner** 选择 Linux / x64，按页面实时提供的下载和注册命令操作。可安装在测试服务器本机，也可安装在能通过 SSH 访问测试服务器的独立机器；注册时增加标签 `project-template-deploy`，并按页面指引安装为系统服务。确认页面状态为 Idle，默认标签为 `self-hosted`、`linux`、`x64`。使用其他架构的 runner 时，按实际架构安装并覆盖下面的 runner 标签。参考 [GitHub 添加 runner 文档](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)。

runner 上需要 Git、Bash、SSH 客户端和 tar。构建与容器冒烟都在托管 runner 执行，测试部署 runner 只上传部署文件并发起 SSH。即便 runner 就在测试机上，也要配置独立的部署 SSH 密钥和主机信息。

保持 PR 工作流使用托管 runner；不要把 PR 或不可信分支的代码执行改到具有内网访问权的部署 runner。手动运行 Deploy 需要仓库写权限，GitHub Environment 的分支规则可以进一步限制可发布的 ref。

如需覆盖默认 runner，在 **仓库级 Settings → Secrets and variables → Actions → Variables** 设置 JSON 标签数组：

| 仓库 Variable | 默认值 |
| --- | --- |
| `TEST_DEPLOY_RUNNER` | `["self-hosted","linux","x64","project-template-deploy"]` |
| `PRODUCTION_DEPLOY_RUNNER` | `["ubuntu-latest"]` |

这两个变量不能放在 Environment 中，因为 runner 选择发生在环境变量可用之前。生产默认使用 GitHub 托管 runner，其必须能访问生产服务器的 SSH 端口；如果服务器仅内网可达，应覆盖为具有相应网络访问能力的 runner。

## 配置 GitHub Environments 与 SSH

在仓库 **Settings → Environments** 创建 `test` 和 `production`，分别填写下面的 Secret 和 Variable。详见 [GitHub Environment 配置](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。

| Environment Secret | 内容 |
| --- | --- |
| `SSH_PRIVATE_KEY` | 对应环境专用、可供非交互登录的 SSH 私钥全文 |
| `SSH_KNOWN_HOSTS` | 已核验服务器 host key 的完整 known_hosts 行 |

| Environment Variable | 内容 |
| --- | --- |
| `SSH_HOST` | runner 实际可达的主机名或 IP；不是本地 `~/.ssh/config` 的别名 |
| `SSH_USER` | 服务器部署账户，例如 `deploy` |
| `SSH_PORT` | 可选，默认 `22` |
| `DEPLOY_PATH` | 可选，留空自动使用远端 `$HOME/apps/project-template/<环境>` |
| `HTTP_BIND` | 可选，覆盖本次发布的监听地址；留空使用服务器 `.env` |
| `HTTP_PORT` | 可选，覆盖本次发布的端口；留空使用服务器 `.env` 的 `18080` |

建议两个环境各生成一对专用 key，将公钥加入各服务器部署账户的 `authorized_keys`，私钥只交给对应 Environment；不要上传个人日常 SSH 私钥。GitHub workflow 使用临时 SSH 配置，不依赖或改写 runner 的个人 `~/.ssh/config`，并在结束时清理私钥。

通过已经可信的 SSH 连接读取服务器公钥：

```bash
ssh "$TEST_SSH_TARGET" 'cat /etc/ssh/ssh_host_ed25519_key.pub'
ssh "$PRODUCTION_SSH_TARGET" 'cat /etc/ssh/ssh_host_ed25519_key.pub'
```

把输出中的 key 类型和 key 数据与 **`SSH_HOST` 的实际值** 拼成 `SSH_KNOWN_HOSTS`。22 端口示例为 `实际主机名 ssh-ed25519 AAAA...`；非 22 端口示例为 `[实际主机名]:2222 ssh-ed25519 AAAA...`。已有可信 known_hosts 记录也可以使用。不要把未经独立核验的 `ssh-keyscan` 输出直接当作信任来源；工作流会强制检查 host key。

建议在 `production` 的 Deployment branches and tags 中分别添加 Branch `main`、Tag `v*` 规则；这会使手动发布其他 ref 被 GitHub 拦截。需要人工发布审批时可另外设置 Required reviewers。仓库的 main 与发布标签也应由可信维护者控制。

GHCR 推送使用工作流自带 `GITHUB_TOKEN`，不需要长期 PAT。包可能默认私有；验证和远端拉取都使用本次任务 token，服务器临时 Docker 登录配置在结束时删除。复用已有 GHCR package 时，需确保该仓库有 package 的 Actions 访问权限。

## 本地 Compose 验证

在仓库根目录运行，使用独立的 `deploy/.env`，不会读取根目录的开发端口文件作为部署配置：

```bash
bash deploy/init-env.sh test "$PWD/deploy"
docker compose --env-file deploy/.env config --quiet
docker compose --env-file deploy/.env build
docker compose --env-file deploy/.env up -d --wait web
curl --fail http://127.0.0.1:18080/api/health
```

浏览器打开 `http://127.0.0.1:18080`。`web` 启动会依次等待数据库、迁移和 API 就绪。需要停止时使用 `docker compose --env-file deploy/.env down`，保留持久化数据卷。

还可验证指定镜像；冒烟脚本使用随机 project、随机数据库密码和随机 loopback 端口，并在完成后清理**自身临时环境**：

```bash
API_IMAGE=project-template-api:local \
WEB_IMAGE=project-template-web:local \
bash scripts/smoke-deploy.sh
```

检查涵盖 Alembic revision、Postgres 与 Redis 连通性、前端 HTML、Nginx 配置与 404 行为，以及 API 写入数据库后替换容器的数据持久性和代理恢复。冒烟成功不代表已配置模型密钥或验证所有业务功能。

部署脚本的失败处理回归测试使用假的 SSH、Docker 和文件锁命令，不连接服务器：

```bash
pnpm exec node --test scripts/deploy.test.mjs
uv run --no-sync pytest api/tests -q
```

## 发布、访问与排查

配置完成并推送工作流后，`main` 推送发布测试，`v*` 标签推送发布生产；也可通过 Run workflow 手动执行。镜像构建完成后，托管 runner 会先进行 Compose 冒烟，成功后才进入服务器部署。

本地手动部署使用相同脚本。先完成上文的 SSH 连接变量配置，将镜像路径与两个 SHA-256 占位值替换为实际值后再运行；摘要只填写 64 位十六进制内容，不包含 `sha256:` 前缀。镜像必须已经发布到 GHCR：

```bash
export IMAGE_PREFIX='ghcr.io/your-org/your-repository'
export API_SHA256='替换为API镜像的实际64位SHA256摘要'
export WEB_SHA256='替换为WEB镜像的实际64位SHA256摘要'
export API_IMAGE="$IMAGE_PREFIX/api@sha256:$API_SHA256"
export WEB_IMAGE="$IMAGE_PREFIX/web@sha256:$WEB_SHA256"

# 根据需要选择一个环境执行。
DEPLOY_SSH_TARGET="$TEST_SSH_TARGET" \
  bash scripts/deploy.sh test "manual-$(date +%Y%m%d%H%M%S)"
DEPLOY_SSH_TARGET="$PRODUCTION_SSH_TARGET" \
  bash scripts/deploy.sh production "manual-$(date +%Y%m%d%H%M%S)"
```

私有镜像需在本地进程环境提供 `GHCR_USER` 和具有 `read:packages` 权限的 `GHCR_TOKEN`，脚本通过 SSH stdin 登录；不要把 token 写入命令参数、提交文件或复制到日志。公开镜像可以不提供。手动部署时始终显式设置 `DEPLOY_SSH_TARGET`；需要自定义 SSH 端口或密钥时，可通过 `DEPLOY_SSH_CONFIG` 指定专用 SSH 配置文件。

从本机访问测试或生产，分别选择一个隧道运行：

```bash
ssh -N -L 18080:127.0.0.1:18080 "$TEST_SSH_TARGET"
ssh -N -L 18080:127.0.0.1:18080 "$PRODUCTION_SSH_TARGET"
```

然后访问 `http://127.0.0.1:18080`。同一个本地端口一次只能开一个隧道；如需并行，把其中一个命令的第一个 `18080` 改为 `18081`。服务器端口若修改过，同步替换隧道右侧端口。

服务器目录结构为：

```text
~/apps/project-template/production/
├── .env                       # 长期保存的服务配置
├── .deploy.lock               # 手动与 Actions 共用的发布锁
├── current -> releases/...    # 最后一次成功发布
└── releases/<release-id>/
    ├── docker-compose.yaml
    ├── images.env             # 镜像 digest 与可选端口覆盖
    └── deploy/apply.sh
```

发布顺序为拉取镜像、等待 Postgres/Redis、运行迁移、更新 API、更新 web、检查 HTTP，最后原子切换 `current`。这是同一 Compose project 的原地更新，可能有短暂服务中断；`current` 是成功记录，并非蓝绿流量切换。失败时 `current` 保持原值，但部分容器或数据库可能已经更新，不能据此认定旧版本仍完整运行。

登录服务器后可查看最后成功版本的服务状态和日志：

```bash
deploy_path="$HOME/apps/project-template/production"
release_path=$(readlink -f "$deploy_path/current")
export DEPLOY_ENV_FILE="$deploy_path/.env"
compose=(docker compose --env-file "$DEPLOY_ENV_FILE" --env-file "$release_path/images.env" -f "$release_path/docker-compose.yaml")
"${compose[@]}" ps -a
"${compose[@]}" logs --tail 100 api web
```

失败发布的详情需将 `release_path` 指向该次 `releases/<release-id>`。GitHub job 日志会保留失败阶段；数据库或迁移失败会阻止后续更新。

## 备份与回滚

发布脚本不自动备份，也不自动逆转迁移。执行有数据结构变化的发布前，应保存数据库备份，并保留此前的镜像 digest。下面在**服务器 Bash 会话**中使用上一节的 `compose` 数组备份 PostgreSQL：

```bash
set -euo pipefail
umask 077
backup_dir="$deploy_path/backups/$(date +%Y%m%d%H%M%S)"
mkdir -p "$backup_dir"
"${compose[@]}" exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_dir/postgres.dump"
cp "$deploy_path/.env" "$backup_dir/deployment.env"
cp "$release_path/images.env" "$backup_dir/images.env"
```

备份包含密钥，应使用受限权限并保存到独立存储，定期演练恢复。Redis 的 AOF 数据和 API 文件分别在 `redis-data`、`api-data` 卷；需要恢复这些数据时，应另外在计划停写后做一致性卷备份。不要用 `docker compose down -v` 停止正式环境，它会删除持久化卷。

人工回滚先确认旧代码与当前数据库结构兼容，再读取旧 release 的 `images.env` 中两个 digest，显式设置对应环境的 `DEPLOY_SSH_TARGET`，以新的 release ID 调用 `scripts/deploy.sh`，例如 `rollback-<时间戳>`。相同脚本会重新检查迁移和健康状态，成功后再更新 `current`。如果旧镜像不认识数据库中较新的 Alembic revision，迁移会停止；此时需要先人工评估兼容修复版本或数据库恢复，不能仅通过切换镜像或 `current` 解决。

需要恢复数据库时先停止业务写入，确认目标实例和备份时间点，再按 PostgreSQL 恢复流程操作。仓库不提供自动 `alembic downgrade` 或自动覆盖数据库的回滚命令。
