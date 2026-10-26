import asyncio
import logging
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

import requests
import uuid_utils as uuid
from google import genai
from google.genai import errors, types
from google.genai.types import GenerateContentResponse, ThinkingLevel
from PIL import Image

from api.core import settings
from api.core.storage import parse_data_url_to_bytes
from api.images.source_access import get_image_reference, guard_image_source
from api.tools.types import ImageToolResponse
from api.utils.object_storage.aliyun_oss import upload_image

logger = logging.getLogger(__name__)

type GeminiProvider = Literal["google", "laozhang"]
type ImageSize = Literal["1K", "2K", "4K"]
type ImageMimeType = Literal["image/png", "image/jpeg", "image/webp"]


class _GeminiToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _failure(model: str | None, code: str, message: str) -> ImageToolResponse:
    return ImageToolResponse(
        image_model=model, content=message, error=code, success=False, images=[]
    )


def _create_client(provider: GeminiProvider) -> genai.Client:
    if provider not in {"google", "laozhang"}:
        raise _GeminiToolError("unsupported_provider", "不支持当前 Gemini 提供商")
    config = getattr(settings.providers, provider)
    if config is None or not config.base_url or not config.api_key.get_secret_value():
        raise _GeminiToolError("provider_unavailable", "Gemini 提供商未配置")
    if provider == "google" and config.use_vertexai:
        raise _GeminiToolError(
            "provider_unavailable", "当前图片工具需要 Gemini Developer API 配置"
        )
    base = config.base_url.rstrip("/").removesuffix("/openai")
    if provider == "laozhang" and base.endswith("/v1"):
        base = base.removesuffix("/v1") + "/v1beta"
    if not urlsplit(base).path.rstrip("/"):
        base += "/v1beta"
    return genai.Client(
        api_key=config.api_key.get_secret_value(),
        http_options=types.HttpOptions(
            base_url=base,
            base_url_resource_scope=types.ResourceScope.COLLECTION,
            client_args={"proxy": settings.proxy_url, "trust_env": False},
            retry_options=types.HttpRetryOptions(attempts=1),
            timeout=175_000,
        ),
    )


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
        raise _GeminiToolError("invalid_image_input", "参考图必须是非空字符串")
    return image_urls


def _image_part(source: str) -> types.Part:
    guard_image_source(source)
    if source.startswith("data:"):
        content = parse_data_url_to_bytes(source)
    elif source.startswith(("https://", "http://")):
        response = get_image_reference(source, timeout=175)
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
            raise _GeminiToolError("invalid_image_input", "不支持当前参考图格式")
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


def handle_gemini_image_response(
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
    try:
        for part in parts:
            # Interim thought images are not the requested final outputs.
            if part.thought:
                continue
            if part.text is not None:
                text.append(part.text)
            if part.inline_data is None:
                continue
            image_bytes = part.inline_data.data
            mime_type = part.inline_data.mime_type
            if not image_bytes or mime_type not in {
                "image/png",
                "image/jpeg",
                "image/webp",
            }:
                raise _GeminiToolError(
                    "provider_invalid_response", "模型返回了无效图片"
                )
            extension = mime_type.split("/")[-1].replace("jpeg", "jpg")
            filename = f"{uuid.uuid7()}.{extension}"
            metadata = asyncio.run(
                upload_image(
                    filename,
                    image_bytes,
                    mime_type=cast(ImageMimeType, mime_type),
                    prefix="creative/gemini",
                    rename=False,
                )
            )
            images.append(metadata.model_dump(mode="json", exclude_none=True))
    except _GeminiToolError as error:
        return _failure(response.model_version, error.code, error.message)
    except Exception as error:
        logger.warning(
            "Gemini image upload failed: error_type=%s", type(error).__name__
        )
        return _failure(
            response.model_version, "image_upload_failed", "生成图片上传失败"
        )
    if not images:
        return ImageToolResponse(
            image_model=response.model_version,
            content="模型未返回图片，请调整提示词后重试",
            error="no_image_returned",
            success=False,
            images=[],
            usage=usage,
        )
    return ImageToolResponse(
        image_model=response.model_version,
        content="\n".join(text),
        success=True,
        images=images,
        usage=usage,
    )


def _generate(
    prompt: str,
    *,
    image_model: str,
    image_urls: str | list[str] | None,
    config: types.GenerateContentConfig,
    provider: GeminiProvider,
    max_images: int = 14,
) -> ImageToolResponse:
    try:
        sources = _image_inputs(image_urls)
        if len(sources) > max_images:
            return _failure(
                image_model,
                "too_many_images",
                f"当前模型最多支持 {max_images} 张参考图",
            )
        contents = [prompt, *[_image_part(source) for source in sources]]
        client = _create_client(provider)
        try:
            response = client.models.generate_content(
                model=image_model, contents=contents, config=config
            )
        finally:
            client.close()
        result = handle_gemini_image_response(response)
        result.image_model = result.image_model or image_model
        return result
    except _GeminiToolError as error:
        return _failure(image_model, error.code, error.message)
    except errors.APIError as error:
        logger.warning(
            "Gemini image request failed: provider=%s status=%s", provider, error.code
        )
        return _failure(
            image_model, "provider_failed", "Gemini 图片生成失败，请检查参数或稍后重试"
        )
    except (OSError, ValueError, requests.RequestException) as error:
        logger.warning("Gemini image input failed: error_type=%s", type(error).__name__)
        return _failure(image_model, "invalid_image_input", "参考图无效或无法读取")
    except Exception as error:
        logger.warning(
            "Gemini image request failed: error_type=%s", type(error).__name__
        )
        return _failure(
            image_model, "provider_failed", "Gemini 图片生成失败，请稍后重试"
        )


def image_create_with_gemini(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
    | None = None,
    image_size: ImageSize | None = None,
    provider: GeminiProvider = "google",
) -> ImageToolResponse:
    return _generate(
        prompt,
        image_model="gemini-3-pro-image",
        image_urls=image_urls,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio, image_size=image_size
            ),
        ),
        provider=provider,
    )


def image_create_with_gemini_flash_2(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal[
        "auto",
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "1:8",
        "8:1",
        "21:9",
    ]
    | None = None,
    image_size: ImageSize | None = None,
    provider: GeminiProvider = "google",
) -> ImageToolResponse:
    return _image_create_with_gemini_flash_2(
        prompt,
        image_model="gemini-3.1-flash-image",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
    )


def image_create_with_gemini_flash_2_1(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal[
        "auto",
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "1:8",
        "8:1",
        "21:9",
    ]
    | None = None,
    image_size: ImageSize | None = None,
    provider: GeminiProvider = "google",
) -> ImageToolResponse:
    return _image_create_with_gemini_flash_2(
        prompt,
        image_model="gemini-nano-banana-2.1",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
    )


def _image_create_with_gemini_flash_2(
    prompt: str,
    *,
    image_model: str,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: ImageSize | None = None,
    provider: GeminiProvider = "google",
) -> ImageToolResponse:
    return _generate(
        prompt,
        image_model=image_model,
        image_urls=image_urls,
        config=types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            response_modalities=["TEXT", "IMAGE"],
            safety_settings=[
                types.SafetySetting(category=category, threshold="OFF")
                for category in (
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_HARASSMENT",
                )
            ],
            thinking_config=types.ThinkingConfig(thinking_level=ThinkingLevel.HIGH),
            image_config=types.ImageConfig(
                aspect_ratio=None if aspect_ratio == "auto" else aspect_ratio,
                image_size=image_size or "2K",
            ),
        ),
        provider=provider,
    )


def image_create_with_gemini_flash(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
    | None = None,
    image_size: ImageSize | None = "1K",
    provider: GeminiProvider = "google",
) -> ImageToolResponse:
    image_model = "gemini-2.5-flash-image"
    if image_size not in {None, "1K"}:
        return _failure(
            image_model,
            "unsupported_image_size",
            "Gemini 2.5 Flash Image 仅支持 1K 图片",
        )
    return _generate(
        prompt,
        image_model=image_model,
        image_urls=image_urls,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        ),
        provider=provider,
        max_images=3,
    )


def magic_generate_with_gemini(
    prompt: str,
    image_url: str,
    *,
    provider: GeminiProvider = "google",
) -> tuple[list[dict], dict | None]:
    result = image_create_with_gemini_flash(
        prompt, image_urls=[image_url], provider=provider
    )
    images = [{**image, "image_url": image["url"]} for image in result.images or []]
    return images, result.usage
