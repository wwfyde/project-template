# 图片工具调用映射与维护

本文是当前 HTTP 入口到 Python 工具的实现参考。每个端点独立维护请求模型和处理函数，参数与对应 `api.tools.images` 函数保持一致；厂商 SDK 请求在工具内部构造。统一返回类型为 `ImageToolResponse`。客户端合同见 [AI 图片工具 API](ai-image-tools.md)。

## 固定映射

路径接在 `/api/ai-tools/images` 后，函数模块位于 `api.tools.images`。

| 固定路径 | 模块与函数 |
| --- | --- |
| `/gemini/gemini-2.5-flash-image` | `gemini.image_create_with_gemini_flash` |
| `/gemini/gemini-3-pro-image` | `gemini.image_create_with_gemini` |
| `/gemini/gemini-3.1-flash-image` | `gemini.image_create_with_gemini_flash_2` |
| `/gemini/gemini-nano-banana-2.1` | `gemini.image_create_with_gemini_flash_2_1` |
| `/seedream/doubao-seedream-4-0-250828` | `seedream.image_create_with_seedream` |
| `/seedream/doubao-seedream-4-5-251128` | `seedream4_5.image_create_with_seedream4_5` |
| `/seedream/doubao-seedream-5-0-260128` | `seedream5_lite.image_create_with_seedream5_lite` |
| `/seedream/doubao-seedream-5-0-pro-260628` | `seedream5_pro.image_create_with_seedream5_pro` |
| `/gpt/gpt-image-2` | `gpt.image_create_with_gpt_image_2` |
| `/gpt/gpt-image-2.5-flare` | `gpt.image_create_with_gpt_image_2_5_flare` |
| `/gpt/gpt-image-2.5-sunburst` | `gpt.image_create_with_gpt_image_2_5_sunburst` |

[路由实现](../src/api/routes/ai_tools.py) 为 11 个字面量路径各写一条显式 `@ai_tools_router.post(...)` 和独立处理函数；没有通配模型路由或路由工厂。Gemini query 默认为 `provider=google`，可选 `laozhang`；GPT 默认为 `openai`，可选 `evolink`；Seedream 只接受 `volcengine`。

GPT 选择 Evolink 时，由 `gpt` 模块调用 [gpt_evolink](../src/api/tools/images/gpt_evolink.py) 对应函数。兼容 Python 函数 `image_create_with_gpt_image_2_5` 保留并委托 Flare，不新增该名称的 HTTP 路由。Qwen 等其他工具虽使用共同上传入口，也没有因此自动注册 HTTP API。

## 参数与结果来源

每个端点在 [schemas/ai_tools.py](../src/api/schemas/ai_tools.py) 中的请求模型直接继承 `BaseModel`，字段、类型、Literal 枚举、默认值和校验配置都在该模型中明确声明，不使用共享请求基类或运行时签名生成。各端点独立维护，调整工具参数时必须同步检查对应模型。

- `prompt` 为必填；其余默认值与对应工具函数一致。
- `provider` 在 query 中声明，body 不含 `provider/model`。
- 请求模型严格校验类型并拒绝额外字段；例如图片列表中的非字符串元素返回 HTTP `422`。
- 每个处理函数都显式传入各参数，直接返回对应模块工具函数的结果。
- 每个处理函数将 `image_urls/mask_url` 原值交给工具，不设置统一的公网、DNS 或本地路径预检查；具体来源、重定向、大小和格式处理由所调用工具负责。请求类型错误返回 HTTP `422`，工具异常仍转换为失败 `ImageToolResponse`。

公共请求字段为 `prompt/image_urls/aspect_ratio/image_size`。GPT 另有 `quality/n`，以及可选的 `size/background/output_format/output_compression/moderation/safety_identifier/mask_url`；具体型号和渠道的支持范围见下节。工具内部的尺寸转换、渠道适配、默认质量和业务校验属于执行合同；Schema 接受参数不代表工具一定能完成当前请求。

路由处理函数是同步 `def`，由 FastAPI 自动放在线程池执行。没有共享工具调度服务。每条路由直接调用工具，失败时在本条路由中构造 [ImageToolResponse](../src/api/tools/types.py)。厂商错误状态、SSE 或任务提交响应不会作为这个 API 的最终响应。

## GPT 执行合同

三款 GPT 公开函数保留旧参数和 `quality="low"`、`n=1` 默认值。GPT Image 2 的质量枚举为 `low/medium/high/auto`；Flare 和 Sunburst 另有 `xhigh/max`。新增7项可选参数默认均为 null；API Schema、显式路由传参和函数签名必须同步维护。

OpenAI 渠道根据 `image_urls` 是否有参考图选择 `images.generate` 或 `images.edit`。直接传 `size` 时禁止同时传非 null 的旧尺寸参数；旧参数仍经过工具换算。透明输出不能使用 JPEG，压缩率仅适用于 JPEG/WebP，`mask_url` 必须配合参考图。完整范围见 [GPT 输出与蒙版编辑](ai-image-tools.md#gpt-输出与蒙版编辑)；官方协议来源为 [Create image](https://developers.openai.com/api/reference/resources/images/methods/generate)、[Create image edit](https://developers.openai.com/api/reference/resources/images/methods/edit)、[输出定制](https://developers.openai.com/api/docs/guides/image-generation#customize-image-output) 和 [图片编辑](https://developers.openai.com/api/docs/guides/image-generation#edit-images)。

参考图读取后验证单帧 PNG/JPEG/WebP、16张数量上限和每张小于50 MiB。蒙版采用带 alpha 的 PNG，尺寸匹配第一张参考图；需要时先将首图 JPEG/WebP 转为 PNG。参考图下载不携带 OpenAI 密钥，凭据只交给服务端配置的 OpenAI 客户端。`safety_identifier` 通过 SDK `extra_body` 传递；编辑请求的 `moderation` 同样通过 `extra_body` 传递，以兼容当前本地 SDK 的显式参数签名。

`input_params` 保存实际调用选项，包括 generate/edit、解析后的尺寸、质量、数量、格式、参考图数量和蒙版标记，以及显式背景/压缩/审核值；不回显提示词、图片数据或安全标识。输出保留上游 `usage`。图片 bytes 校验并上传后直接采用 OSS `ImageInfo`，上传失败返回 `image_upload_failed`，可携带此前成功上传的结果；空输出返回 `no_image_returned`，异常数据返回 `provider_invalid_response`。

Evolink 委托原有对应工具，只接受旧参数合同；任何非 null 的新增选项，以及 `xhigh/max`，在渠道分派前返回 `unsupported_provider_parameter`。这些字段不得通过丢弃、替换或假装成功来兼容。其轮询、下载和最终统一响应行为保持不变。全部 GPT 路由仍是同步最终响应，不增加 `stream/partial_images` 或 SSE。

## 执行与上传链路

```text
固定 POST 端点
  → 本端点独立请求模型校验
  → FastAPI 在线程池运行本端点同步处理函数
  → 原值传参并显式调用对应工具
  → 厂商 SDK / HTTP 调用
  → 取得图片 bytes
  → asyncio.run(aliyun_oss.upload_image(...))
  → ImageInfo.model_dump(...)
  → ImageToolResponse
```

Evolink 在取得图片 bytes 前还会创建任务、轮询完成并下载输出，等待整个流程结束再返回。这个内部轮询不形成对外任务查询协议。

图片统一交给 [api.utils.object_storage.aliyun_oss.upload_image](../src/api/utils/object_storage/aliyun_oss.py)。它根据 PNG/JPEG/WebP bytes 提取元数据，上传 OSS，返回同一对象的 URL、标识、对象键及 SHA-256。工具应直接保存其 `ImageInfo.model_dump(...)`，不再另外创建 ID、拼装 URL 或丢弃 `storage_key/sha256`。

同步工具在工作线程中调用 `asyncio.run`，每次上传需要独立 OSS async client，不能跨这些 event loop 缓存复用客户端。`cdn` 仅决定返回的访问基址，OSS bucket、region、endpoint 和访问密钥仍来自服务端 `oss` 配置。

## 维护原则

1. 新增模型时写独立请求模型、显式路由装饰器和独立处理函数，在函数内直接调用图片工具；不引入路由工厂、动态模型生成或共享调度服务。
2. 工具签名或默认值变化时，同步更新对应请求模型和显式调用参数，再检查 OpenAPI，防止独立维护的两侧发生偏差。
3. 新增输出图片必须走同一个 OSS 上传函数，统一 `ImageInfo` 元数据，不回退到本地文件存储。
4. AI 工具端点不执行调用方身份认证，不依赖 `X-Api-Key` 或 `images.clients`；仅使用服务端 `settings.providers` 的渠道密钥进行上游鉴权。图片引用交由具体工具处理；工具异常使用 `ImageToolResponse`，请求模型的类型/枚举校验使用 HTTP 错误。
5. 用 mock SDK/HTTP/OSS 验证实际函数、渠道分派、上传 bytes、元数据与失败行为；集成测试确认固定路由只调用选中的函数。
6. 文档记录当前函数实际默认值和归一化行为，不把厂商功能表当成已经暴露的 API 能力。

主要源码：[Gemini 工具](../src/api/tools/images/gemini.py)、[Seedream 4.0](../src/api/tools/images/seedream.py)、[4.5](../src/api/tools/images/seedream4_5.py)、[5.0 Lite](../src/api/tools/images/seedream5_lite.py)、[5.0 Pro](../src/api/tools/images/seedream5_pro.py)、[GPT 工具](../src/api/tools/images/gpt.py)、[Evolink 工具](../src/api/tools/images/gpt_evolink.py)。
