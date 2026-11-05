from api.tools.images.utils import decode_data_url
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Literal, get_args

import httpx2
import requests
import uuid_utils as uuid
from google import genai
from google.genai import types
from google.genai.types import GenerateContentResponse, ThinkingLevel
from PIL import Image

from api.core import settings
from api.tools.images.types import GeminiImageGenerationParams
from api.tools.types import GeminiImageModel, ImageToolResponse
from api.utils.object_storage import upload_image

type GeminiProvider = Literal["google"]
type ImageSize = Literal["1K", "2K", "4K"]


class GeminiToolError(Exception):
    """A Gemini input or response failure for callers to handle."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@asynccontextmanager
async def _create_client() -> AsyncGenerator[genai.Client]:
    config = settings.providers.google
    if config is None:
        raise GeminiToolError("provider_unavailable", "Gemini 提供商未配置")

    async with httpx2.AsyncClient(
        proxy=settings.proxy_url, trust_env=False, timeout=175, follow_redirects=True
    ) as http_client:
        client = genai.Client(
            api_key=config.api_key.get_secret_value(),
            http_options=types.HttpOptions(
                base_url=config.base_url,
                base_url_resource_scope=types.ResourceScope.COLLECTION,
                client_args={"proxy": settings.proxy_url, "trust_env": False},
                httpx_async_client=http_client,
                retry_options=types.HttpRetryOptions(attempts=1),
                timeout=175_000,
            ),
        )
        try:
            yield client
        finally:
            try:
                await client.aio.aclose()
            finally:
                client.close()


def _image_inputs(image_urls: str | list[str] | None) -> list[str]:
    if image_urls is None:
        return []
    if isinstance(image_urls, str):
        # A data URL contains a comma; it is one reference, not a URL list.
        if image_urls.startswith("data:"):
            return [image_urls]
        return [
            item.strip()
            for item in image_urls.replace("，", ",").split(",")
            if item.strip()
        ]
    if not all(isinstance(item, str) and item for item in image_urls):
        raise GeminiToolError("invalid_image_input", "参考图必须是非空字符串")
    return image_urls


def _image_part(source: str) -> types.Part:
    if source.startswith("data:"):
        content = decode_data_url(source)
    elif source.startswith(("https://", "http://")):
        response = requests.get(source, timeout=175)
        response.raise_for_status()
        content = response.content
    else:
        path = Path(source)
        if not path.is_absolute():
            path = settings.data_dir / "files" / path
        content = path.read_bytes()

    with Image.open(BytesIO(content)) as image:
        mime_type = Image.MIME.get(image.format or "")
        if mime_type is None:
            raise GeminiToolError("invalid_image_input", "不支持当前参考图格式")
        if len(content) > 20 * 1024 * 1024:
            image.thumbnail((1024, 1024))
            output = BytesIO()
            if "A" in image.getbands():
                image.save(output, format="PNG", optimize=True)
                mime_type = "image/png"
            else:
                image.convert("RGB").save(
                    output, format="JPEG", quality=85, optimize=True
                )
                mime_type = "image/jpeg"
            content = output.getvalue()
    return types.Part.from_bytes(data=content, mime_type=mime_type)


async def handle_gemini_image_response(
    response: GenerateContentResponse, *, include_usage: bool = True
) -> ImageToolResponse:
    usage = (
        response.usage_metadata.model_dump(exclude_none=True)
        if include_usage and response.usage_metadata
        else None
    )
    parts = response.parts or []
    images: list[dict] = []
    text = []
    for part in parts:
        # Interim thought images are not the requested final outputs.
        if part.thought:
            continue
        if part.text is not None:
            text.append(part.text)
        if part.inline_data is None:
            continue
        image_bytes = part.inline_data.data
        mime_type = str(part.inline_data.mime_type)
        if not image_bytes or mime_type not in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise GeminiToolError("provider_invalid_response", "模型返回了无效图片")
        extension = mime_type.split("/")[-1].replace("jpeg", "jpg")
        filename = f"{uuid.uuid7()}.{extension}"
        metadata = await upload_image(
            filename,
            image_bytes,
            mime_type=mime_type,
            prefix="creative/gemini",
            rename=False,
        )
        images.append(metadata.model_dump(mode="json", exclude_none=True))
    if not images:
        raise GeminiToolError("no_image_returned", "模型未返回图片，请调整提示词后重试")
    return ImageToolResponse(
        image_model=response.model_version,
        content="\n".join(text),
        success=True,
        images=images,
        usage=usage,
    )


async def _prepare_request(
    prompt: str,
    model: GeminiImageModel,
    image_urls: str | list[str] | None,
    aspect_ratio: str | None,
    image_size: ImageSize | None,
) -> tuple[types.ContentListUnionDict, types.GenerateContentConfig]:
    if model not in get_args(GeminiImageModel.__value__):
        raise GeminiToolError("unsupported_model", "不支持当前 Gemini 图片模型")
    if model == "gemini-3.1-flash-lite-image":
        if image_size not in {None, "1K"}:
            raise GeminiToolError(
                "unsupported_image_size", "Gemini 3.1 Flash Lite Image 仅支持 1K 图片"
            )
        image_size = "1K"
    sources = _image_inputs(image_urls)
    if len(sources) > 14:
        raise GeminiToolError("too_many_images", "当前模型最多支持 14 张参考图")
    image_config = types.ImageConfig(
        aspect_ratio=None if aspect_ratio == "auto" else aspect_ratio,
        image_size=image_size,
    )
    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"], image_config=image_config
    )
    if model in {"gemini-3.1-flash-image", "gemini-nano-banana-2.1"}:
        config.temperature = 1
        config.top_p = 0.95
        config.safety_settings = [
            types.SafetySetting(
                category=category, threshold=types.HarmBlockThreshold.OFF
            )
            for category in (
                types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            )
        ]
        config.thinking_config = types.ThinkingConfig(thinking_level=ThinkingLevel.HIGH)
        image_config.image_size = image_size or "2K"
    return [prompt, *[_image_part(source) for source in sources]], config


async def image_create_with_gemini(
    prompt: str,
    *,
    model: GeminiImageModel = "gemini-3.1-flash-lite-image",
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: ImageSize | None = None,
    provider: GeminiProvider = "google",
    allow_grounding: bool = True,
) -> ImageToolResponse:
    """Generate and upload images; callers handle validation, SDK, and I/O errors."""
    contents, config = await _prepare_request(
        prompt,
        model,
        image_urls,
        aspect_ratio,
        image_size,
    )
    if allow_grounding and model in {
        "gemini-3.1-flash-image",
        "gemini-nano-banana-2.1",
    }:
        config.tools = [
            types.Tool(
                google_search=types.GoogleSearch(
                    search_types=types.SearchTypes(
                        web_search=types.WebSearch(),
                        image_search=types.ImageSearch(),
                    )
                )
            )
        ]
    config_params = config.model_dump(mode="json", exclude_none=True)
    config_params.update(config_params.pop("image_config", {}))
    generation_params = GeminiImageGenerationParams(
        prompt=prompt,
        images=_image_inputs(image_urls) or None,
        model=model,
        provider=provider,
        **config_params,
    )
    async with _create_client() as client:
        response = await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
    generation_params.model_version = response.model_version
    result = await handle_gemini_image_response(response)
    result.image_model = result.image_model or model

    result.generation_params = generation_params
    result.instructions = prompt
    return result


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(image_create_with_gemini(prompt="生成一碗牛肉"))
    print(result)
