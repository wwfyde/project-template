# Skills：本地存储、版本和预览

Skills API 管理包含 `SKILL.md` 的版本化文件包。资源字段、版本操作及下载路径对齐 [OpenAI Skills API](https://developers.openai.com/api/reference/resources/skills) 与 [Skills 指南](https://developers.openai.com/api/docs/guides/tools-skills)，元数据保存在本项目 PostgreSQL，文件包保存在配置的阿里云 OSS。创建、读取和预览不会上传到 OpenAI，也不会调用模型或执行包内脚本。

接口同时挂载在 `/api/skills` 和 `/v1/skills`；两者操作同一组本地资源。路径和资源模型兼容不代表身份认证兼容：所有请求需要本项目登录 Cookie，写请求还需要 `X-CSRF-Token`。OpenAI Bearer API key 不能访问这些端点。身份校验、CSRF 和账户访问规则见 [接口参考](api-reference.md#1-服务入口与认证约定)。

浏览器调用 `/v1/skills` 需要 Redis 会话配置 `session_cookie_path="/"`，让登录 Cookie 覆盖这个前缀；既有 `session_cookie_path="/api"` 仅覆盖 `/api/skills`。服务不会自动修改全局 Cookie 路径。

## 存储边界

生产实现固定使用 PostgreSQL 和已有 `[oss]` 配置，不通过 `repo_type=in-memory` 切换为临时数据。OSS 中保存私有 ZIP，HTTP 下载和文件预览均先校验资源归属；数据库保存目录清单，因此展开树不需要下载 ZIP。

数据库表采用单数形式：

| 表 | 用途 |
| --- | --- |
| `skill` | 资源归属、创建时间、默认/最新版本指针和下一个版本号。 |
| `skill_version` | 不可变版本的名称、描述、文件清单和对象存储 key。 |
| `skill_object_deletion` | 等待删除的对象 key；数据库提交成功后重试物理删除。 |

先配置 API 的 PostgreSQL、Redis 登录会话和 `[oss]` 参数，然后在 `api/` 工作目录执行迁移。迁移会创建上述表，不向 OpenAI 发送数据：

```bash
uv run alembic upgrade head
```

OSS 凭据和 bucket 设置沿用 [配置示例](../config.example.toml)。Skills 对象使用独立的 `skills/` 前缀，便于对账和清理，不复用图片的 `oss.prefix`；不要给该前缀配置公共读取或经公开 CDN 绕过应用鉴权。

## 标准端点

下表路径相对于 `/api/skills`，也可使用 `/v1/skills`。成功状态均为 `200`；下载返回 `application/zip`，其他响应为 JSON。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | 空路径 | 上传文件包，创建 skill 及版本 `"1"`。 |
| GET | 空路径 | 按创建时间分页列出当前调用方可访问的 skill。 |
| GET | `/{skill_id}` | 读取 skill。 |
| POST | `/{skill_id}` | JSON `{"default_version":"2"}`，修改默认版本。 |
| DELETE | `/{skill_id}` | 删除 skill 及全部版本。 |
| GET | `/{skill_id}/content` | 下载默认版本 ZIP。 |
| POST | `/{skill_id}/versions` | 上传不可变新版本；可选表单字段 `default=true`。 |
| GET | `/{skill_id}/versions` | 按数值版本号分页列出版本。 |
| GET | `/{skill_id}/versions/{version}` | 读取指定版本。 |
| DELETE | `/{skill_id}/versions/{version}` | 删除指定版本。 |
| GET | `/{skill_id}/versions/{version}/content` | 下载指定版本 ZIP。 |

`Skill` 包含 `id`、`object="skill"`、`created_at`、`name`、`description`、`default_version`、`latest_version`。`SkillVersion` 包含 `id`、`object="skill.version"`、`created_at`、`name`、`description`、`skill_id`、`version`。时间为 Unix 秒，版本号在 HTTP 中始终是字符串。

删除 skill 返回 `id`、`object="skill.deleted"`、`deleted=true`；删除版本返回 `id`、`object="skill.version.deleted"`、`deleted=true` 和 `version`。

两个列表接受 `after`、`limit`、`order`。默认 `limit=20`、`order=desc`，`limit` 范围为 `0..100`，`order` 可选 `asc` 或 `desc`。`after` 是上一页最后一个资源的 **ID**；版本分页使用版本 ID，不能用 `"2"` 代替。响应为 `object="list"`、`data`、`first_id`、`last_id`、`has_more`；空页的两个 ID 为 `null`。`limit=0` 返回空页，`has_more` 仍表示该游标之后是否存在记录。

上传内容或版本参数非法返回 `400`，资源不存在或不可访问返回 `404`。版本游标属于另一可访问 skill 时返回 `400`。认证、CSRF 与请求字段校验沿用应用错误响应，调用方不能假设所有错误都具有 OpenAI 的错误格式。

## 上传与校验

按官方指南使用 `multipart/form-data`，每次请求选用以下一种方式：

- ZIP：字段 `files` 包含一个 ZIP 文件。
- 目录：重复的 `files[]` 字段包含每个文件，`filename` 必须保留顶层文件夹与内部相对路径。

参考页把上传体展示为 JSON 的 `files: string|string[]`，与指南中的 multipart 示例不同。本实现使用指南的 multipart 上传协议，不接受服务器文件路径，也不通过请求中的路径或 URL 读取任意外部文件。

包必须包含一个顶层文件夹，且该文件夹根部有唯一的 `SKILL.md`，例如：

```text
report-helper/
├── SKILL.md
├── references/
│   └── style.md
└── scripts/
    └── report.py
```

`SKILL.md` 文件名匹配不区分大小写；整个包只能有一个这样的 manifest。名称与描述从 YAML frontmatter 的 `name`、`description` 提取。拒绝 YAML 别名，以免解析不可信 manifest 时产生引用展开。

| 校验项 | 本地限制 |
| --- | --- |
| ZIP 上传大小 | 50 MiB。 |
| 单个解压文件大小 | 25 MiB。 |
| 全部文件解压后的总大小 | 50 MiB。 |
| 文件数 | 最多 500。 |
| ZIP 压缩方式 | 仅接受 Stored（不压缩）和 DEFLATE；拒绝 BZIP2、LZMA 等方式。 |
| 文件相对路径 | UTF-8 编码后最多 1024 字节，最多 32 层。 |
| 路径与 ZIP 条目 | 拒绝绝对路径、路径穿越、链接、加密 ZIP、重复路径，以及文件/目录冲突。 |

官方指南列出 50 MB ZIP、25 MB 单文件和 500 文件；本实现明确使用 MiB，并增加总解压量及路径限制。这些本地边界用于控制上传和预览资源消耗。

上传成功后会把经过校验的文件重新打包为规范 ZIP，下载不会逐字节复现原始 ZIP。这样即使输入 ZIP 的声明大小与实际压缩内容不一致，也不会保留未校验的压缩尾部。文件内容和包内路径保留；普通文件权限规范为 `0644`，ZIP 内已有执行位的文件规范为 `0755`，清除特殊权限位。目录 multipart 不传递执行权限。空目录、ZIP 注释与原始时间等归档元数据不保留。

## 版本规则

每个新 skill 从 `"1"` 开始。创建版本采用数据库事务分配单调递增的版本号，删除后不复用，避免旧链接指向不同内容。版本内容不可修改；变更文件需要创建新版本。

`default_version` 决定不指定版本时的内容；`latest_version` 指向仍存在的最高版本。创建版本默认不切换默认指针，传 `default=true` 才切换。skill 顶层的 `name`、`description` 跟随默认版本，版本对象保留该次上传自己的名称和描述。删除最新版本后，`latest_version` 回退到剩余最大版本号。本地读取接口也接受 `latest` 别名；删除版本和设置默认版本必须提供明确的正整数版本字符串。

存在其他版本时不能删除默认版本，应先切换默认版本；只剩一个版本时，删除它会同时删除 skill。删除 skill 会级联删除全部版本。这里“只剩一个版本”的例外对应官方 OpenAPI 中禁止删除默认版本的条件：仍有其他版本。

数据库与 OSS 没有共享事务。上传后若数据库写入失败，服务会补偿删除已上传对象；删除资源时，数据库事务同时写入 `skill_object_deletion`，后台每 30 秒重试物理删除，失败的 key 保留供下次重试。删除请求成功表示资源已从 API 移除，不表示 OSS 已立即完成删除。

进程在对象上传后、数据库提交或补偿记录前被强制终止，仍可能留下未登记对象。运维应定期对账专属 Skills 前缀与数据库中的存活对象及删除队列，留出正在上传的缓冲期，再清理确认无引用的旧对象。

## 树与内容预览扩展

以下是本项目新增的预览端点，不属于 OpenAI 标准接口；与标准端点采用相同的登录和资源归属校验。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/{skill_id}/tree` | 默认版本的目录树与文件元数据。 |
| GET | `/{skill_id}/versions/{version}/tree` | 指定版本的目录树与文件元数据。 |
| GET | `/{skill_id}/files?path=...` | 预览默认版本中的一个文件。 |
| GET | `/{skill_id}/versions/{version}/files?path=...` | 预览指定版本中的一个文件。 |

`path` 使用树接口返回的完整包内相对路径，包括顶层文件夹，例如 `report-helper/SKILL.md`，不接受宿主机文件路径。树由已校验并存入数据库的 manifest 构建，不需要解压文件到服务端目录。

树响应为 `object="skill.tree"`、`skill_id`、`version`、`nodes`、`file_count` 和 `total_bytes`。节点包含 `name`、`path`、`type`、`size`、`media_type`、`children`，目录排在文件前面。空目录没有文件清单条目，因此不会单独出现在树中。

文件响应为 `object="skill.file"`、`skill_id`、`version`、`path`、`size`、`media_type`、`encoding`、`content`、`truncated` 和 `reason`。文本预览返回 UTF-8 纯文本，最大 256 KiB；超限时在完整字符边界截断并设置 `truncated=true`。二进制或非 UTF-8 文件的 `content`、`encoding` 为 `null`，`reason="binary_or_non_utf8"`，仍保留元数据。前端对文本进行转义显示，不执行脚本，不把上传的 HTML、Markdown 或 SVG 作为可执行页面渲染。下载使用 `content` 接口获取完整 ZIP。

前端 `/skills` 管理页提供上传、版本管理和预览。业务页面可从 [Skills 模块](../../web/src/features/skills/index.ts) 复用 `SkillTree`（可选中的树）、`SkillFilePreview`（内容及加载/错误状态）、`SkillPreview`（连接目录与远程文件预览）和 `createSkillClient`，无需自行解析 ZIP 或拼装对象存储地址。

## 调用示例

以下在本地终端执行。`skills.cookies` 是已完成登录后保存的 Cookie jar，`<session-csrf-token>` 替换为该会话的 CSRF token；Cookie 名称取决于会话配置。示例中的上传路径都由 curl 在客户端读取。不要填写真实凭据后提交到仓库。

```bash
SKILL_API=http://localhost:8000/api/skills
SKILL_CSRF='<session-csrf-token>'

# 创建 skill：ZIP 中包含 report-helper/ 顶层文件夹。
curl --fail-with-body -b skills.cookies "$SKILL_API" \
  -H "X-CSRF-Token: $SKILL_CSRF" \
  -F 'files=@./report-helper.zip;type=application/zip'

# 或者通过文件目录上传创建 skill。
curl --fail-with-body -b skills.cookies "$SKILL_API" \
  -H "X-CSRF-Token: $SKILL_CSRF" \
  -F 'files[]=@./report-helper/SKILL.md;filename=report-helper/SKILL.md' \
  -F 'files[]=@./report-helper/scripts/report.py;filename=report-helper/scripts/report.py'

SKILL_ID='<created-skill-id>'

# 创建版本并设为默认版本。
curl --fail-with-body -b skills.cookies "$SKILL_API/$SKILL_ID/versions" \
  -H "X-CSRF-Token: $SKILL_CSRF" \
  -F 'files=@./report-helper-v2.zip;type=application/zip' \
  -F 'default=true'

# 单独切换默认版本。
curl --fail-with-body -b skills.cookies "$SKILL_API/$SKILL_ID" \
  -H "X-CSRF-Token: $SKILL_CSRF" \
  -H 'Content-Type: application/json' \
  -d '{"default_version":"1"}'

# 树和单文件预览只读，不要求 CSRF。
curl --fail-with-body -b skills.cookies "$SKILL_API/$SKILL_ID/tree"
curl --fail-with-body -b skills.cookies --get "$SKILL_API/$SKILL_ID/files" \
  --data-urlencode 'path=report-helper/SKILL.md'

# 下载指定版本；写入客户端当前目录。
curl --fail-with-body -b skills.cookies \
  "$SKILL_API/$SKILL_ID/versions/1/content" -o downloaded-skill.zip

# 删除 skill：API 资源立即移除，对象物理删除可稍后重试完成。
curl --fail-with-body -b skills.cookies -X DELETE "$SKILL_API/$SKILL_ID" \
  -H "X-CSRF-Token: $SKILL_CSRF"
```
