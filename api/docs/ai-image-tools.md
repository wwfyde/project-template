# AI 图片工具 API

这组 API 直接调用 `api.tools.images` 中已有的图片函数。每个固定模型端点都有独立的请求 Schema 和显式处理函数，按对应工具的参数和默认值直接调用；结果统一为 `ImageToolResponse`，生成图片通过 Aliyun OSS 上传完成后才返回。

## 固定端点与渠道

以下路径均为 `POST`，接在 `/api/ai-tools/images` 后。`provider` 放在 query，省略时使用默认渠道。

| 固定路径 | 默认 provider | 可选 provider |
| --- | --- | --- |
| `/gemini/gemini-2.5-flash-image` | `google` | `laozhang` |
| `/gemini/gemini-3-pro-image` | `google` | `laozhang` |
| `/gemini/gemini-3.1-flash-image` | `google` | `laozhang` |
| `/gemini/gemini-nano-banana-2.1` | `google` | `laozhang` |
| `/seedream/doubao-seedream-4-0-250828` | `volcengine` | — |
| `/seedream/doubao-seedream-4-5-251128` | `volcengine` | — |
| `/seedream/doubao-seedream-5-0-260128` | `volcengine` | — |
| `/seedream/doubao-seedream-5-0-pro-260628` | `volcengine` | — |
| `/gpt/gpt-image-2` | `openai` | `evolink` |
| `/gpt/gpt-image-2.5-flare` | `openai` | `evolink` |
| `/gpt/gpt-image-2.5-sunburst` | `openai` | `evolink` |

例如 `/gpt/gpt-image-2.5-flare?provider=evolink` 调用对应 Evolink 工具，工具创建任务、轮询完成、下载结果并上传 OSS，然后返回统一图片结果。没有任意模型路由，也没有 Qwen HTTP 入口。

## 请求参数

请求使用 `Content-Type: application/json`，body 不含 `model` 或 `provider`。这组端点不执行调用方身份认证，不需要 `X-Api-Key`、登录 Cookie、CSRF 或 `images.clients`；即使携带旧 Cookie，也不会加载 Redis 会话。

模型鉴权由工具使用服务端 `settings.providers` 中对应渠道的 `api_key` 完成。请求中的 `X-Api-Key` 或 `Authorization` 不会成为上游凭据，也不影响该入口是否可调用。

| 参数 | 类型 | 默认值 / 行为 |
| --- | --- | --- |
| `prompt` | string，必填 | 图片生成或编辑指令 |
| `image_urls` | string、string[] 或 null | 默认 null；参考图片地址或图片 data URL |
| `aspect_ratio` | string 或 null | 默认 null；各工具支持范围见下表 |
| `image_size` | string 或 null | 各工具枚举和默认值见下表 |
| `quality` | 仅 GPT；2 支持 `low/medium/high/auto`，2.5 Flare / Sunburst 另支持 `xhigh/max` | 三款工具默认均为 `low`；扩展档位仅用于 OpenAI 渠道 |
| `n` | 仅 GPT，integer | 默认 `1`；工具执行时要求 1–10 |

每个端点的请求模型在 [schemas/ai_tools.py](../src/api/schemas/ai_tools.py) 中独立声明，字段类型、Literal 枚举及默认值与对应工具函数保持一致。必填缺失、类型错误、Literal 不匹配或多余字段返回 `422`；业务约束由工具处理，可能返回 `success=false`。

**图片引用：**路由按请求 Schema 校验参数类型，并将 `image_urls` 和 GPT 的 `mask_url` 原值交给对应工具，不再统一检查公网地址、DNS 或本地文件路径。非字符串图片引用仍返回 HTTP `422`。推荐多图使用数组；字符串拆分、URL/data URL/本地文件是否支持、重定向处理及图片大小和格式限制均以具体工具实现为准。

### 比例、尺寸与默认值

| 工具对应模型 | `aspect_ratio` | `image_size` 类型枚举 | 函数默认值 |
| --- | --- | --- | --- |
| Gemini 2.5 Flash Image | 下述 A 组 | `1K/2K/4K` 或 null | `1K`；实际传 2K/4K 时工具返回 `unsupported_image_size` |
| Gemini 3 Pro Image | A 组 | `1K/2K/4K` 或 null | null |
| Gemini 3.1 Flash Image / Nano Banana 2.1 | B 组 | `1K/2K/4K` 或 null | null；当前工具内部按 2K 调用 |
| Seedream 4.0 | string 或 null，由工具转换比例/宽高 | `1K/2K/4K` 或 null | `2K` |
| Seedream 4.5 / 5.0 Lite | string 或 null，由工具转换比例/宽高 | `2K/4K` 或 null | `2K` |
| Seedream 5.0 Pro | string 或 null，由工具转换比例/宽高 | `1K/2K/4K` 或 null | `2K`；当前函数将 4K 归一化为 2K |
| GPT Image 2 / 2.5 Flare / 2.5 Sunburst | string 或 null，由工具处理比例/宽高 | `1K/2K/4K` 或 null | null |

A 组：`1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, 21:9`。

B 组：`auto, 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 1:8, 8:1, 21:9`。

这些是当前工具函数合同。HTTP 不接受厂商的 `contents`、`generationConfig`、`stream` 或 `watermark`；GPT 支持下述额外输出与编辑参数，Gemini 和 Seedream 不因此增加同名字段。底层 SDK 参数由工具构造。省略参数时使用本端点中与工具函数一致的默认值，显式 null 则按函数内部逻辑处理。

### GPT 输出与蒙版编辑

三款 GPT 端点保留 `prompt/image_urls/aspect_ratio/image_size/quality/n`，另提供下列可选字段，默认均为 null。`provider` 仍在 query 中，默认 `openai`。

| 参数 | 类型 / 可选值 | 行为 |
| --- | --- | --- |
| `size` | string，`auto` 或 `WIDTHxHEIGHT` | 直接指定输出尺寸；不可同时提供非 null 的 `aspect_ratio` 或 `image_size` |
| `background` | `auto/opaque/transparent` | 透明背景须使用 PNG 或 WebP；JPEG 不支持透明输出 |
| `output_format` | `png/jpeg/webp` | 未指定时工具使用 PNG |
| `output_compression` | integer，0–100 | 只可配合 JPEG 或 WebP 输出 |
| `moderation` | `auto/low` | 传入 OpenAI 审核设置 |
| `safety_identifier` | string，最长128字符 | 传入上游安全标识；不作为本服务身份凭据 |
| `mask_url` | string，由 GPT 工具读取的图片引用 | 需要至少一张参考图，蒙版作用于第一张参考图 |

OpenAI 渠道无参考图时调用 `client.images.generate`，有参考图时调用 `client.images.edit`。`prompt` 要求1–32000字符的非空文本，`n` 为1–10。GPT 2.5 两款支持 `xhigh/max`，GPT Image 2 保持 `low/medium/high/auto`；工具默认质量仍为 `low`。这些选项对应官方 [生成接口](https://developers.openai.com/api/reference/resources/images/methods/generate) 与 [编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit)。

自定义宽高必须同时满足：两边均为16的整数倍、单边不超过3840、长短边比例不超过3:1、总像素在655360–8294400之间。原有 `aspect_ratio/image_size` 方式由工具换算成合法尺寸；不提供尺寸相关参数时使用 `auto`。尺寸与透明/压缩输出说明见 [OpenAI 输出定制](https://developers.openai.com/api/docs/guides/image-generation#customize-image-output)。

OpenAI 编辑支持最多16张参考图，工具接受有效的单帧 PNG/JPEG/WebP，单张参考图和蒙版均须小于50 MiB。当前 `mask_url` 要求带 alpha 通道的 PNG，尺寸与第一张参考图一致；第一张参考图如果是 JPEG/WebP，工具会先转为 PNG，再连同蒙版提交。透明区域指示待编辑区域。输入规范与多图蒙版语义参考 [OpenAI 图片编辑指南](https://developers.openai.com/api/docs/guides/image-generation#edit-images)；HTTP 请求体仍受下文的20 MiB + 128 KiB限制。

Evolink 继续使用原有 `prompt/image_urls/aspect_ratio/image_size/quality/n` 工具合同。以上新增字段只要传入非 null 值，或质量选择 `xhigh/max`，就返回 HTTP `200`、`success=false`、`error=unsupported_provider_parameter`；不会静默丢弃这些选项。Evolink 仍会完成任务轮询和 OSS 上传后返回最终图片。

## 调用示例

前提：已配置模型渠道和 OSS，无需配置调用方 key。以下 curl 命令执行时会实际调用工具；图片地址为示例占位值。

```bash
IMAGE_API=http://localhost:8000/api/ai-tools/images

# Seedream 4.5，默认 volcengine。
curl -sS "$IMAGE_API/seedream/doubao-seedream-4-5-251128" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"蓝色陶瓷杯的产品摄影，纯白背景","aspect_ratio":"1:1","image_size":"2K"}'

# Nano Banana 2，默认 Google。
curl -sS "$IMAGE_API/gemini/gemini-3.1-flash-image" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"蓝色陶瓷杯的产品摄影，纯白背景","aspect_ratio":"1:1","image_size":"2K"}'

# 同一工具选择 Laozhang；参考图由工具读取。
curl -sS "$IMAGE_API/gemini/gemini-3.1-flash-image?provider=laozhang" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"将杯子改成蓝色","image_urls":["https://example.com/source.png"],"image_size":"2K"}'

# GPT Image 2.5 Flare，默认 OpenAI。
curl -sS "$IMAGE_API/gpt/gpt-image-2.5-flare" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"蓝色陶瓷杯的产品摄影，纯白背景","aspect_ratio":"1:1","image_size":"2K","quality":"low","n":1}'

# GPT Image 2.5 Flare：透明 WebP、扩展质量及原生尺寸；不同时传旧尺寸参数。
curl -sS "$IMAGE_API/gpt/gpt-image-2.5-flare" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"蓝色陶瓷杯产品图，透明背景","size":"1536x1024","quality":"xhigh","background":"transparent","output_format":"webp","output_compression":80,"n":1}'

# 同一模型选择 Evolink，等待任务完成和 OSS 上传后返回。
curl -sS "$IMAGE_API/gpt/gpt-image-2.5-flare?provider=evolink" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"蓝色陶瓷杯的产品摄影，纯白背景","aspect_ratio":"1:1","image_size":"2K","quality":"low","n":1}'
```

## 统一响应

所有工具使用 [ImageToolResponse](../src/api/tools/types.py)，不直接透传厂商 JSON、HTTP 状态或 SSE。HTTP 请求等待工具完成后返回一个 JSON 对象。

| 字段 | 含义 |
| --- | --- |
| `success` | 工具是否成功；调用方必须检查 |
| `content` | 工具文本或失败说明 |
| `error` | 可选错误代码；部分工具失败时仍可能为 null |
| `image_model` | 工具报告的模型 |
| `images` | 上传结果列表；每项为 `ImageInfo` 的序列化结果 |
| `usage` | 工具保留的用量信息，可为 null |
| `input_params` | 工具记录的实际参数，可为 null |
| `data` | 工具的附加数据，可为 null |

图片元数据保留 OSS 上传结果的 `url`、`id`、`filename`、`original_filename`、`storage_key`、`sha256`、`width`、`height`、`mime_type`、`image_format` 等。`file_size` 在当前 `ImageInfo` 序列化器中是带 KB/MB 单位的字符串，不是字节数整数。字段是否出现以工具实际返回为准。

Evolink 的异步任务 ID 是内部执行细节；其工具完成轮询、下载和 OSS 上传后才返回 `images`。其他工具也使用同一个上传函数，不返回尚未上传的厂商临时地址。

OpenAI GPT 结果的 `input_params` 记录实际的 `operation`、尺寸、质量、数量、输出格式、参考图数量和是否带蒙版，以及已提供的背景、压缩、审核选项；保留上游 `usage` 和 OSS 元数据。`safety_identifier`、提示词、参考图片数据不复制到该参数摘要。多图处理发生部分上传失败时，`success=false` 的响应可能保留此前成功上传的 `images`，应以整体状态判断本次请求是否完成。

## 配置、上传与执行

需要两类服务端配置，详见 [config.example.toml](../config.example.toml)：

1. `providers.google/laozhang/volcengine/openai/evolink`：按实际使用的渠道配置 `api_key` 和 `base_url`；密钥仅用于工具向上游厂商鉴权。
2. `oss`：`bucket_name`、`access_key_id`、`access_key_secret`，以及可选 `region`、`endpoint`、`prefix`、`cdn`。

`images.clients` 只控制外部私有图片资产 API `/api/v1/images`，不控制这组 AI 图片工具端点。

`cdn` 可配置图片访问域名；省略时上传函数使用 OSS 公网域名。工具提供自己的对象前缀，例如 `creative/gpt`。返回 URL 能否被客户端读取取决于 Bucket/CDN 的既有访问配置。

唯一图片上传入口是 [api.utils.object_storage.aliyun_oss.upload_image](../src/api/utils/object_storage/aliyun_oss.py)：异步上传图片 bytes，返回 `ImageInfo`。同步图片工具通过 `asyncio.run(...)` 调用它，每次上传创建并关闭独立 OSS 客户端。每条同步 `def` 路由直接调用对应工具，FastAPI 自动在线程池运行该处理函数，避免阻塞 API 事件循环。

图片生成功能不再写入本地公开文件目录。此入口也不创建私有图片资产版本或评论；相关能力仍使用 [图片编辑 API](image-editing.md)。

## 错误与验证

| HTTP 状态 / 结果 | 含义 |
| --- | --- |
| `404` | 没有该固定模型路径 |
| `413` | JSON 解析前请求体超过 20 MiB + 128 KiB 硬上限 |
| `422` | JSON 语法错误，或必填参数、类型、枚举、额外字段、provider 无效 |
| `200` + `success=false` | 工具无法读取或处理图片引用，或其他业务失败，例如模型渠道或 OSS 未配置、生成失败、超时或上传失败 |

不把 HTTP 200 视为生成成功。工具异常会统一转换为失败 `ImageToolResponse`，不会把原始异常里的凭据回传。超时和轮询行为取决于具体工具；该 HTTP 层没有 SSE 或独立后台任务协议。

请求尚未进入工具就返回422时，会额外产生一条 ERROR 事件 `http.request.validation_failed`。日志包含 Request-ID、路由、错误数量和字段位置（如 `body.quality`、`query.provider`）；JSON 解析错误使用 `json_invalid`，并记录从1开始的行/列和从0开始的 Unicode 字符偏移（如 `body@23`）。JSON 尾逗号会明确显示 `Trailing comma is not allowed`。`validation.errors` 保存经过过滤的错误 JSON，最多记录20项；不记录请求体、拒绝值、headers 或异常堆栈，未知输入字段名和自定义校验消息会简化。

只传 `{"prompt":"生成一碗牛肉面"}` 是合法请求，其他参数使用默认值；`{"prompt":"生成一碗牛肉面",}` 含尾逗号，JSON 解析即失败，不会调用模型。Uvicorn 的 access log 和 `HTTP request completed` 仍表示请求完成，具体错误应查看同一 Request-ID 的 ERROR 验证事件。

GPT 工具常见业务错误码包括 `invalid_parameters`（尺寸或选项组合错误）、`invalid_mask`、`invalid_image_input`、`image_input_too_large`、`too_many_images`、`unsupported_provider_parameter`、`provider_unavailable`、`provider_auth_failed`、`provider_rate_limited`、`provider_timeout`、`provider_invalid_response`、`no_image_returned` 和 `image_upload_failed`；其他模型请求异常归为 `provider_failed`。这些仍通过 `ImageToolResponse.success=false` 返回，区别于请求模型的 HTTP `422`。

GPT 上游调用失败时，日志事件 `image.request.failed` 和响应 `data.diagnostics` 会保留诊断字段：`provider`、`model`、`operation`、实际请求 `size`、上游 `status`、`upstream_host`、`upstream_request_id`、`local_request_id`、`exception_type`、渠道 `error_code/error_type/error_param/error_message` 以及工具耗时 `elapsed_ms`。未提供的上游字段为 null。错误说明先脱敏再限制为512字符，不返回整段厂商响应、请求 headers、提示词、图片数据或带签名的 URL。

`provider=openai` 代表配置槽，实际请求主机取决于 `settings.providers.openai.base_url`，可能是兼容网关。`InternalServerError` 只能说明 SDK 收到5xx；应查看 `diagnostics.status` 和渠道错误说明。响应仍遵守本地 `200 + success=false` 合同，所以 access log 的 HTTP200 不代表上游成功；本地 Request-ID 和上游 request ID 也不是同一个编号。

只传 `image_size="4K"` 时，当前 GPT 工具默认换算为 `2880x2880` 方图。竖版请求还应提供 `aspect_ratio`，或改用明确的合法 `size` 并省略 `aspect_ratio/image_size`。提示词中的比例文字不会替代显式尺寸参数。这个布局选择不能单独解释上游5xx。

离线测试使用模拟 SDK/HTTP/OSS，不需要真实模型调用。例如从仓库根目录运行：

```bash
uv run --no-sync pytest api/tests/test_ai_image_routes.py api/tests/test_gpt_image_tools.py
```

模拟测试验证调用、参数和结果合同，不表示真实账户的模型权限、网络、计费或 OSS 访问策略已完成在线验证。工具映射和维护规则见 [图片工具调用参考](ai-image-models-reference.md)。
