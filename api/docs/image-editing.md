# 图片预览、编辑与对外 API

资产页支持上传并预览图片，底部工具栏提供 Markup（标注）、Comment（定位评论）、Remove BG（去背景）、Erase（选区擦除）和 Resize（缩放）。前端与外部服务共用 `ImageService`，HTTP 协议不包含厂商 SDK 类型或凭据。

## 实现边界

| 操作 | 执行方式 | 结果 |
| --- | --- | --- |
| Markup | 本地 Pillow；画笔、文字、矩形、椭圆 | 合成后的新图片版本 |
| Comment | 本地存储；归一化坐标定位 | 图片版本下的评论记录，不修改图片 |
| Remove BG | GPT Image 或 veImageX | 经透明通道校验的 PNG |
| Erase | GPT 原生 mask；Gemini/Seedream 参考 mask | 服务端用 mask 合成，选区外像素保持原图 |
| Resize | 本地 Pillow；contain / cover / stretch | 精确目标尺寸；contain 默认透明留白 |

编辑始终创建不可变子资产，`parent_id` 指向输入版本。前端撤销/重做切换版本，不重复请求模型；未应用的标注和选区也可撤销/重做。评论只属于当时的图片版本。标注应用后烘焙进图片，当前没有可跨会话继续编辑的矢量图层。

普通缩放不会生成新画面，当前没有 AI 扩图。模型返回尺寸不同时会重采样至原图尺寸，再做 mask 合成。选区内的修复质量由模型决定；边缘灰度 mask 参与混合，黑色区域逐像素保留。服务不会把 mask 参考图当成厂商原生 mask 支持，也不会将不透明输出伪装为抠图成功。

## API 和认证

两套入口具有相同资源、请求和响应：

- `/api/images`：本项目前端，要求有效登录 Cookie；写操作必须携带 `X-CSRF-Token`，并遵循现有 Origin 校验。
- `/api/v1/images`：外部服务，要求 `X-Api-Key`，在 `images.clients` 中配置。独立于 `auth.header` 示例密钥；不依赖浏览器 Cookie、CSRF 或 Redis 会话。

另有直接调用生图函数的 [AI 图片工具 API](ai-image-tools.md)，路径为 `/api/ai-tools/images`。该工具入口不执行调用方身份认证，也不依赖 `images.clients`；模型密钥来自服务端 `settings.providers`，只用于上游鉴权。本文两套私有资产入口的认证和资源隔离规则保持不变。

浏览器资源按 account + user 隔离；外部资源按配置中的 client ID 隔离。两套入口不能互读同一个 ID。客户端不能通过 `User-ID` / `Tenant-ID` 等 header 声明资源所有权。轮换同一 client ID 的 key 不改变资源归属，删除 client 配置立即停止该客户端的新请求。

下表路径接在对应入口之后：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/providers` | 能力、是否配置、启用模型、默认模型和 mask 类型 |
| POST | `/assets` | multipart `file`，可选 `purpose=image\|mask`；返回 201 |
| GET | `/assets?limit=50` | 当前调用方最近的图片；limit 1–100，mask 不入列表 |
| GET | `/assets/{id}` | 图片元数据 |
| GET | `/assets/{id}/content` | 经鉴权的 PNG；`?download=true` 下载 |
| POST | `/assets/{id}/edits` | 提交编辑，等待结果，返回 201 新资产 |
| GET / POST | `/assets/{id}/comments` | 列出或添加定位评论 |
| DELETE | `/assets/{id}/comments/{comment_id}` | 删除评论，返回 204 |

资产包含 `id, filename, width, height, mime_type, purpose, parent_id, operation, provider, model, created_at, content_url`。`content_url` 是当前 API 入口的相对鉴权路径；外部下载仍需附加 key。服务不接收任意远程源 URL 或服务器文件路径，避免把图片编辑接口变成网络代理。

模型选择使用 `provider` + `model`，provider 为 `local / gpt / gemini / seedream / veimagex`。未传 model 时选择该 provider 的默认值。`GET /providers` 返回服务端启用列表，列表之外的模型被拒绝。`configured=true` 表示必要配置存在，并不代表账号权限、计费或网络已通过在线验证。

### 外部调用示例

从任何有 curl 和 jq 的终端执行。`IMAGE_API_KEY` 由部署方提供，勿将实际值写进仓库。

```bash
IMAGE_API=http://localhost:8000/api/v1/images

curl -fsS "$IMAGE_API/providers" -H "X-Api-Key: $IMAGE_API_KEY"

IMAGE_ID=$(curl -fsS "$IMAGE_API/assets" \
  -H "X-Api-Key: $IMAGE_API_KEY" \
  -F 'file=@source.png' | jq -r '.id')

curl -fsS "$IMAGE_API/assets/$IMAGE_ID/edits" \
  -H "X-Api-Key: $IMAGE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"operation":"resize","provider":"local","width":1200,"height":800,"fit":"contain"}'

# 以下操作会调用收费模型；模型 ID 必须在服务端启用列表中。
curl -fsS "$IMAGE_API/assets/$IMAGE_ID/edits" \
  -H "X-Api-Key: $IMAGE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"operation":"remove_background","provider":"gpt","model":"gpt-image-2.5-sunburst"}'

MASK_ID=$(curl -fsS "$IMAGE_API/assets" \
  -H "X-Api-Key: $IMAGE_API_KEY" \
  -F 'purpose=mask' -F 'file=@mask.png' | jq -r '.id')

curl -fsS "$IMAGE_API/assets/$IMAGE_ID/edits" \
  -H "X-Api-Key: $IMAGE_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"operation\":\"erase\",\"provider\":\"gpt\",\"mask_asset_id\":\"$MASK_ID\"}"
```

mask 必须与 EXIF 方向归一化后的原图尺寸一致，使用**不透明灰度 PNG，白色编辑、黑色保留**。全黑 mask、不同尺寸或其他调用方的 mask 在调用模型前被拒绝。GPT adapter 会将它转换成原生透明区域 mask。

标注请求示例（`width` 是原图像素；文字中表示字号）：

```json
{
  "operation": "markup",
  "provider": "local",
  "markup": [
    {"kind": "path", "points": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.3}], "color": "#ef4444", "width": 6},
    {"kind": "text", "points": [{"x": 0.2, "y": 0.1}], "color": "#ffffff", "width": 32, "text": "标题"}
  ]
}
```

矩形/椭圆使用两个对角点；所有点坐标为 0–1。每次最多 200 项、每项 2000 点、合计 10000 点。文字最长 500 字符；非 ASCII 文字需要覆盖该文字的服务端字体，配置 `images.font_path`。未配置时会查找 macOS PingFang 或 Linux Noto Sans CJK，找不到则明确报错。

添加评论的 JSON 为 `{"text":"调整这里的文字","x":0.2,"y":0.3}`，最长 2000 字符。评论不发送给模型。

## 配置模型和 veImageX

图片配置位于 `[images]`，详见 [config.example.toml](../config.example.toml)。普通模型沿用现有 credentials：

| provider | Settings 字段 / TOML 别名 | 请求协议 |
| --- | --- | --- |
| gpt | `providers.openai` | `/images/edits` multipart |
| gemini | `providers.google` / `[providers.gemini]` | 原生 `models/{model}:generateContent` |
| seedream | `providers.volcengine` / `[providers.ark]` | 方舟 `/images/generations` |
| veimagex | `images.veimagex` | 官方 SDK 上传、GetSegmentImage、GetResourceURL |

`images.gpt_models / gemini_models / seedream_models` 控制模型白名单；已有 `providers.*.image_model` 若配置，会加入对应列表并成为默认值。不会用文本模型 `providers.*.model` 代替图片模型。Gemini adapter 使用 Developer API key，暂不支持 Vertex AI；现有 `/v1beta/openai` 兼容地址会转为原生 `/v1beta`。

veImageX 需要独立 AK/SK、ServiceId、CDN 域名及保留 PNG alpha 的原图模板。内置模型选择为 `productv2`（商品）和 `humanv2`（人像），不作为通用生成模型。SDK 上传的是图片 bytes，不会要求把项目私有文件暴露为公网 URL。返回的下载地址只允许已配置的 HTTPS CDN 主机，拒绝重定向，随后保存到本项目的私有资产存储。上传到 veImageX 的远端原图与结果受该服务自己的存储和计费策略管理，本服务不自动删除远端对象。

当前 veImageX 只声明去背景；未核验的擦除 mask 语义和 CDN 缩放模板没有冒充成已实现能力。添加 provider 时实现 `ImageProvider.info` 和 `edit(ProviderInput) -> bytes`，在 `build_providers()` 注册即可；不必改变 route、前端协议或存储。

## 存储、执行和限制

`repo_type=in-memory` 适合单进程开发，重启丢失数据；生产选择 `postgres`，运行以下迁移（在 `api/` 目录）：

```bash
uv run alembic upgrade head
```

新增单数表 `image_asset`、`image_comment`。图片 bytes 暂存 PostgreSQL BYTEA，元数据为 JSONB。没有写入公开 `/api/files` 目录；下载和评论始终检查归属。后续大规模部署可用同一 `ImageStore` 协议替换为对象存储。当前没有图片删除、自动保留期或存储配额，运维需安排数据库及 veImageX 对象生命周期管理。

默认限制为上传/归一化输出各 10 MiB、1600 万像素、单边 8192；仅接受单帧 PNG/JPEG/WebP。EXIF 旋转被应用，元数据在 PNG 重编码时清除。HTTP 流在解析前有 20 MiB + 128 KiB 硬上限，之后执行配置的较小图片限制。缩放后的尺寸也受像素预算约束。

`max_concurrent_edits` 是每进程图片处理容量（含上传归一化），默认 2；占满返回 429。多 worker 的总容量为各进程之和，未实现全局限流/客户预算。外部服务部署应在网关配置请求频率、总上传量和费用预算。

编辑运行在当前 HTTP 请求内，默认模型超时 180 秒。当前没有任务队列、后台恢复、任务轮询、webhook、幂等键或自动重试。请求超时或断开后供应商仍可能计费；不要盲目重发。反向代理需允许相应的响应等待时间。未完成编辑不创建新资产；成功返回前会保存完整结果。

业务错误为 `{"detail":{"code":"...","message":"..."}}`：400/422 参数或能力错误，401 未认证，403 CSRF/Origin 不通过，404 不存在或无权访问，413 大小超限，429 本地容量已满，502 厂商失败/无效输出，503 缺少配置或厂商限流，504 模型超时。参数校验使用 FastAPI 的 422 detail 列表但不回显 input；厂商错误不暴露原始响应或密钥。

## 验证和参考

从仓库根目录运行离线测试，不产生收费模型调用：

```bash
uv run pytest api/tests/test_image_service.py api/tests/test_image_routes.py api/tests/test_image_store.py api/tests/test_image_providers.py
pnpm --filter web run check-types
pnpm --filter web run test
```

存储测试使用内存和 SQLite 事务适配验证读写、隔离、回滚与迁移；这不替代目标 PostgreSQL 的上线迁移验证。供应商测试验证请求/响应契约和异常，实际账号权限与图像效果需要部署后用已开通模型验收。

接口映射参考 [OpenAI Image generation](https://developers.openai.com/api/docs/guides/image-generation)、[Gemini Generate Content 图片文档](https://ai.google.dev/gemini-api/docs/generate-content/image-generation?hl=en)、[Seedream 图片 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=en)、[veImageX 智能去背景](https://docs.volcengine.com/docs/veImageX/Intelligentbackgroundremoval?lang=zh)及[火山引擎 Python SDK](https://github.com/volcengine/volc-sdk-python)。模型 ID 是可配置的启用列表，账号是否具备访问权限由供应商决定。
