# Responses 内置图片工具的输入可见性

核查日期：2026-11-04。范围为 OpenAI 官方 Responses API 的 `image_generation` 内置工具；本地交叉核对 Python SDK `openai==3.31.0`。本文是接口研究，不修改应用实现，也未使用密钥或执行真实模型请求。

**可以取得部分真实调用信息，但不能从公开 Response 还原完整的图像模型调用参数。** `image_generation_call.revised_prompt` 是公开的改写后提示词；同一对象还可能返回质量、尺寸等元数据。公开 schema 没有通用 `arguments`、本次实际选用的输入图片列表或内部请求体。[图片工具指南](https://developers.openai.com/api/docs/guides/tools-image-generation#revised-prompt)、[Response 返回结构](https://developers.openai.com/api/reference/resources/responses/methods/retrieve)

## 三类信息应分别记录

| 信息 | 读取位置 | 能证明什么 |
| --- | --- | --- |
| 应用提交的提示词、图片、工具选项 | 调用前保存的 `input`、`tools`、会话引用 | 应用提交给 Responses 的请求；不能证明模型最终为某次图片调用选择了哪些图片 |
| 工具定义与配置 | `response.tools` | 本次 Response 可用的工具配置；不是按每个 `image_generation_call` 返回的调用参数 |
| 公开的图片调用结果与元数据 | `response.output` 中所有 `type == "image_generation_call"` 项 | 每个调用的 ID、状态、图片结果，以及服务实际返回的可选字段 |

`response.tools` 的文档语义是模型可以调用的工具数组。图片工具支持在请求配置中设置质量、尺寸、格式等选项，也允许某些选项使用 `auto`。[Response 工具字段](https://developers.openai.com/api/reference/resources/responses/methods/retrieve)、[图片工具选项](https://developers.openai.com/api/docs/guides/tools-image-generation#tool-options)

## 可以直接读取的字段

| 字段 | 文档定义与边界 |
| --- | --- |
| `revised_prompt` | 经过模型提示词改写后实际使用的提示词；不等于用户原始提示词，也不表示全部内部上下文 |
| `quality` | 生成图片的质量；可选，允许 `low/medium/high/xhigh/max/auto` |
| `size` | 图片尺寸，可选的 `WIDTHxHEIGHT` 字符串 |
| `output_format` | 生成使用的输出格式，可选的 `png/webp/jpeg` |
| `background` | 生成使用的背景设置，可选，仍允许 `auto` |
| `action` | 生成使用的操作，可选，允许 `generate/edit/auto` |
| `id`、`status`、`result` | 调用 ID、调用状态、Base64 图片结果；`result` 允许为 null |

这些元数据是公开 schema 中的字段，但**不能保证每次都返回，也不能保证 `auto` 必然解析为具体值**。缺失或 null 应记录为未知，不能拿请求配置补成“实际值”。`output_compression`、`input_fidelity`、输入图片清单和完整 `arguments` 均不在该调用结果的公开字段中。[ImageGenerationCall schema](https://developers.openai.com/api/reference/resources/responses/methods/retrieve)

下面的函数只检查已经取得的 Python SDK `Response`，不会发起请求；保留所有图片调用，包括没有图片结果的失败调用。图片 Base64 单独处理，null 字段从精简元数据中省略。

```python
from openai.types.responses import Response


def image_call_metadata(response: Response) -> list[dict]:
    return [
        item.model_dump(mode="json", exclude={"result"}, exclude_none=True)
        for item in response.output
        if item.type == "image_generation_call"
    ]
```

应用可另存 `response.id`、原始请求记录和图片结果引用。不要把应用记录字段命名为上游实际 `arguments`；建议分开命名为 `request_config` 与 `image_call_metadata`。这里是记录方式建议，不是新增的 OpenAI API 字段。

当前项目的 [Responses 图片处理循环](/Users/wwfyde/projects/project-template/api/src/api/tools/images/gpt.py:178) 已将调用元数据写入 `ImageToolResponse.generation_params`，类型为 `GPTImageGenerationParams`。按业务要求，非 null 的调用结果字段优先，其次使用 `response.tools` 中的图片工具配置，最后回填实际发送的 `ImageGeneration` 配置（来自 `ImageParam`，包含图片模型 `model`）。不使用顶层 `response.model`，因为它是主模型。上游 `revised_prompt` 映射为 `generation_params.prompt`，未返回时回填原始提示词，原始指令另存于 `ImageToolResponse.instructions`；显式空字符串仍会保留。单次调用返回参数模型，多次调用放在 `generation_params.calls` 中分别保存，没有调用时返回配置回填值；失败调用也会保留，`result` 图片 Base64 被排除。Images API 分支同样返回该模型和原始指令，其参数来自实际请求及图片 API 的返回值。因此该字段包含请求配置回填值，不能把每个值都视为服务确认的实际调用参数。

## 补查和流式接口的边界

| 途径 | 可得到的内容 | 不能据此得到的内容 |
| --- | --- | --- |
| `responses.retrieve(response_id)` | 对仍可检索的响应，重新读取 Response 和图片调用公开字段 | 不会变成内部图片调用的额外调试接口 |
| `responses.input_items.list(response_id)` | 用于生成这次 Response 的输入项，支持分页 | 没有逐个图片调用的“选中参考图”映射 |
| `include=["message.input_image.image_url"]` | 补充输入消息中的图片 URL | 不是 `image_generation_call` 的输入图片清单；公开 include 枚举没有 `image_generation_call.arguments` |
| 流式 `response.output_item.done` 或最终 `response.completed` | 完成的输出项或 Response，可读取上述图片调用字段 | 没有额外的完整图片调用参数事件 |
| `response.image_generation_call.partial_image` | 预览图；可选 `background/output_format/quality/size` | 不含提示词或输入图片清单 |
| `response.image_generation_call.in_progress/generating/completed` | 调用 ID、输出索引、事件序号和事件类型 | 这些进度事件本身不含完整调用对象、最终图片或 `arguments` |

接口与事件定义见 [Retrieve](https://developers.openai.com/api/reference/resources/responses/methods/retrieve)、[List input items](https://developers.openai.com/api/reference/resources/responses/subresources/input_items/methods/list)、[Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events)。上述“不能”指目前公开接口没有此项保证或字段，不推断服务内部实现。

以下是可选补查方式的示意，**会发起 API 请求，本文没有执行**；需要已有 `AsyncOpenAI` 客户端和仍可检索的响应 ID，代码放在异步函数中执行。

```python
stored = await client.responses.retrieve(response_id)
metadata = image_call_metadata(stored)

# SDK 迭代器处理分页。这里拿到的是 Response 输入项。
inputs = [
    item async for item in client.responses.input_items.list(
        response_id,
        include=["message.input_image.image_url"],
        order="asc",
    )
]
```

图片输入可来自 URL、Base64 data URL 或 Files API 的文件 ID；多轮还可能引用前序 Response 或图片调用 ID。因此，保存完整请求和历史引用有助于重建**可用的图片上下文**，但不能把它当成每次内部图片调用的精确选图证据。若业务需要复现来源，建议应用另外保存输入文件的稳定标识、内容哈希和顺序。[图片输入与多轮生成](https://developers.openai.com/api/docs/guides/image-generation)

原始 HTTP 响应、SDK `model_dump()` 和客户端 HTTP 日志只能观察服务公开返回或应用实际发送的数据。依据上述公开协议，不能据此承诺恢复服务内部的模型间请求；要求模型自行描述“刚才用了哪些参数”也不能代替调用记录。这是协议可观测范围的判断，不是官方承诺存在隐藏查询接口。

## 需要准确记录 prompt、图片与质量时

如果只需要一次生成或编辑，直接使用 Images API，并在应用发请求前保存 `prompt`、`image`/`mask` 引用和 `quality/size` 等选项。官方将这一 API 定位于单次生成或编辑场景。[Image API 与 Responses API 的选择](https://developers.openai.com/api/docs/guides/image-generation#choosing-the-right-api)

如果还需要主模型决定提示词、选图和质量，可定义自有 function tool，例如 `render_image(prompt, image_ids, quality, size)`。模型返回 `function_call.arguments`，应用解析、校验并记录，再调用 Images API。如此可以审计**模型传给自有函数的参数**和**应用提交给 Images API 的请求**；仍不声称能观察 OpenAI 内部的全部处理。[Function calling](https://developers.openai.com/api/docs/guides/function-calling)

## 本地 SDK 交叉核对

`openai==3.31.0` 的 `ImageGenerationCall` 明确定义上述可选字段，没有 `arguments` 或输入图片列表；`ResponseIncludable` 与部分图像事件也与官方文档一致。对应本地源码：

- [ImageGenerationCall](/Users/wwfyde/projects/project-template/.venv/lib/python3.14/site-packages/openai/types/responses/response_output_item.py:125)
- [ResponseIncludable](/Users/wwfyde/projects/project-template/.venv/lib/python3.14/site-packages/openai/types/responses/response_includable.py:7)
- [ResponseImageGenCallPartialImageEvent](/Users/wwfyde/projects/project-template/.venv/lib/python3.14/site-packages/openai/types/responses/response_image_gen_call_partial_image_event.py:12)

验证限于当前官方文档和本地 SDK 类型。未针对账号、具体模型组合、第三方兼容接口实测字段覆盖率；这些情况下应以收到的原始响应为准，不将字段缺失填充为推测值。
