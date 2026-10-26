"""Synchronous GPT image tools with validated inputs and canonical OSS outputs."""

import asyncio
import base64
import binascii
import json
import logging
import re
import time
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

import httpx2
import openai
from openai import OpenAI
from openai.types import ImagesResponse
from PIL import Image

from api.core import settings
from api.core.request_context import get_request_context
from api.images.source_access import ImageSourceError, guard_image_source
from api.tools.images import gpt_evolink
from api.tools.types import ImageToolResponse
from api.utils.object_storage.aliyun_oss import upload_image

logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_REFERENCE_IMAGES = 16


class _GPTToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _failure(
    model: str,
    code: str,
    message: str,
    *,
    input_params: dict | None = None,
    usage: dict | None = None,
    images: list[dict] | None = None,
    diagnostics: dict | None = None,
) -> ImageToolResponse:
    return ImageToolResponse(
        image_model=model,
        content=message,
        error=code,
        success=False,
        images=images or [],
        input_params=input_params,
        usage=usage,
        data={"diagnostics": diagnostics} if diagnostics is not None else None,
    )


def _diagnostic_text(
    value: object, private_values: list[str], limit: int = 512
) -> str | None:
    """Redact before truncating; never serialize the entire upstream error body."""
    if not isinstance(value, str):
        return None
    # Gateway messages sometimes embed another JSON document with escaped '/'.
    # Normalize those slashes before matching URLs, data URIs and known inputs.
    text = re.sub(r"\\+/", "/", value)
    for private in sorted(set(private_values), key=len, reverse=True):
        if not private:
            continue
        for variant in {
            private,
            json.dumps(private, ensure_ascii=False)[1:-1],
            json.dumps(private, ensure_ascii=True)[1:-1],
            quote(private, safe="", errors="replace"),
        }:
            text = text.replace(re.sub(r"\\+/", "/", variant), "<REDACTED>")
    text = re.sub(
        r"data:[^\s,;]+(?:;[^\s,]+)*;base64,[a-zA-Z0-9+/=_-]+", "<REDACTED>", text
    )
    text = re.sub(r"https?://[^\s\"'<>]+", "<REDACTED>", text)
    text = re.sub(r"\bsk-[a-zA-Z0-9_-]+", "<REDACTED>", text)
    text = re.sub(r"(?i)\b(?:bearer\s+)[a-zA-Z0-9._~+/-]+=*", "Bearer <REDACTED>", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|authorization|password|token|secret|signature|prompt)"
        r"\s*(?:[:=]|\bis\b)\s*(?:\"[^\"]*\"|'[^']*'|[^;,\r\n]+)",
        r"\1=<REDACTED>",
        text,
    )
    text = re.sub(r"\b[a-zA-Z0-9+/=_-]{80,}\b", "<REDACTED>", text)
    # Token-like secrets without a key/value label must not become error text.
    text = re.sub(
        r"(?i)\b[a-zA-Z0-9_-]+[-_](?:secret|token|password|signature)(?:[-_][a-zA-Z0-9_-]+)?\b",
        "<REDACTED>",
        text,
    )
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    return text[:limit]


def _diagnostic_identifier(value: object, private_values: list[str]) -> str | None:
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-zA-Z0-9_.:\[\]-]{1,160}", value
    ):
        return None
    return value if _diagnostic_text(value, private_values) == value else None


def _provider_failure(
    error: Exception,
    *,
    image_model: str,
    provider: str,
    input_params: dict,
    started_at: float,
    base_url: str | None,
    private_values: list[str],
) -> ImageToolResponse:
    status = getattr(error, "status_code", None)
    status = status if type(status) is int else None
    if isinstance(error, openai.APIResponseValidationError):
        code, content = "provider_invalid_response", "模型返回了无效响应"
    elif isinstance(error, (openai.APITimeoutError, httpx2.TimeoutException)):
        code, content = "provider_timeout", "模型调用超时"
    elif status in {401, 403}:
        code, content = "provider_auth_failed", "模型渠道认证失败或无访问权限"
    elif status == 429:
        code, content = "provider_rate_limited", "模型渠道繁忙或配额不足，请稍后重试"
    elif status is not None:
        code = "provider_failed"
        content = (
            f"上游图片接口返回 HTTP {status}，请查看 data.diagnostics 中的渠道错误信息"
        )
    else:
        code, content = "provider_failed", "GPT 图片请求失败，请查看 data.diagnostics"

    body = error.body if isinstance(error, openai.APIStatusError) else None
    detail = body.get("error", body) if isinstance(body, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    response = getattr(error, "response", None)
    upstream_id = getattr(error, "request_id", None)
    if not upstream_id and isinstance(response, httpx2.Response):
        upstream_id = response.headers.get("x-request-id") or response.headers.get(
            "request-id"
        )
    request = getattr(error, "request", None)
    try:
        host = (
            request.url.host
            if isinstance(request, httpx2.Request)
            else urlsplit(base_url or "").hostname
        )
    except ValueError:
        host = None
    message = _diagnostic_text(detail.get("message"), private_values)
    context = get_request_context()
    diagnostics = {
        "provider": provider,
        "model": image_model,
        "operation": input_params.get("operation"),
        "size": input_params.get("size"),
        "status": status,
        "upstream_host": _diagnostic_identifier(host, private_values),
        "upstream_request_id": _diagnostic_identifier(upstream_id, private_values),
        "local_request_id": context.request_id if context is not None else None,
        "exception_type": type(error).__name__,
        "error_code": _diagnostic_identifier(detail.get("code"), private_values),
        "error_type": _diagnostic_identifier(detail.get("type"), private_values),
        "error_param": _diagnostic_identifier(detail.get("param"), private_values),
        "error_message": message
        or (
            f"Upstream returned HTTP {status} without a structured error message."
            if status is not None
            else content
        ),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    logger.warning(
        "GPT image request failed: provider=%s host=%s model=%s operation=%s upstream_status=%s upstream_request_id=%s",
        provider,
        diagnostics["upstream_host"],
        image_model,
        diagnostics["operation"],
        status,
        diagnostics["upstream_request_id"],
        extra={
            **diagnostics,
            "tool_success": False,
            "tool_error": code,
            "otel.event.name": "image.request.failed",
        },
    )
    return _failure(
        image_model, code, content, input_params=input_params, diagnostics=diagnostics
    )


def _dimensions(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([1-9][0-9]{0,4})x([1-9][0-9]{0,4})", value)
    if match is None:
        raise _GPTToolError("invalid_parameters", "尺寸必须为 auto 或整数 WIDTHxHEIGHT")
    width, height = map(int, match.groups())
    dimensions = (width, height)
    if not gpt_evolink.is_valid_gpt_size(*dimensions):
        raise _GPTToolError(
            "invalid_parameters", "尺寸不符合模型的边长、比例或像素限制"
        )
    return dimensions


def _resolve_size(
    size: str | None, aspect_ratio: str | None, image_size: str | None
) -> str:
    if image_size not in {None, "1K", "2K", "4K"}:
        raise _GPTToolError("invalid_parameters", "不支持当前 image_size")
    if size is not None:
        if not isinstance(size, str):
            raise _GPTToolError("invalid_parameters", "size 必须是字符串")
        if aspect_ratio is not None or image_size is not None:
            raise _GPTToolError(
                "invalid_parameters", "size 不能与 aspect_ratio/image_size 同时传入"
            )
        if size == "auto":
            return size
        width, height = _dimensions(size)
        return f"{width}x{height}"
    if aspect_ratio in {None, "auto"}:
        if image_size is None or aspect_ratio == "auto":
            return "auto"
        aspect_ratio = "1:1"
    if not isinstance(aspect_ratio, str):
        raise _GPTToolError("invalid_parameters", "aspect_ratio 必须为比例或整数宽高")
    if any(separator in aspect_ratio for separator in ("x", "X", "×")):
        width, height = _dimensions(aspect_ratio.replace("X", "x").replace("×", "x"))
        return f"{width}x{height}"
    match = re.fullmatch(r"([1-9][0-9]{0,4}):([1-9][0-9]{0,4})", aspect_ratio)
    if match is None:
        raise _GPTToolError("invalid_parameters", "aspect_ratio 必须为整数比例")
    width, height = map(int, match.groups())
    if max(width, height) > 3 * min(width, height):
        raise _GPTToolError("invalid_parameters", "图片长短边比例不能超过 3:1")
    resolved = gpt_evolink.calculate_custom_size(width, height, image_size or "1K")
    if resolved is None:
        raise _GPTToolError("invalid_parameters", "无法计算所请求的图片尺寸")
    return resolved


def _sources(image_urls: str | list[str] | None) -> list[str]:
    if image_urls is not None and not isinstance(image_urls, (str, list)):
        raise _GPTToolError("invalid_image_input", "参考图片必须是字符串或字符串列表")
    sources = gpt_evolink.normalize_image_urls(image_urls)
    if len(sources) > MAX_REFERENCE_IMAGES:
        raise _GPTToolError("too_many_images", "最多支持 16 张参考图片")
    if any(not isinstance(source, str) or not source.strip() for source in sources):
        raise _GPTToolError("invalid_image_input", "参考图片必须是非空字符串")
    return sources


def _read_source(source: str, client: httpx2.Client) -> bytes:
    """Read a bounded reference without sending provider credentials to its host."""
    try:
        guard_image_source(source)
        if source.startswith("data:"):
            match = re.fullmatch(
                r"data:image/(?:png|jpeg|jpg|webp);base64,(.+)", source
            )
            if match is None:
                raise _GPTToolError("invalid_image_input", "图片 data URL 格式无效")
            encoded = match.group(1)
            if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
                raise _GPTToolError(
                    "image_input_too_large", "参考图片或蒙版必须小于 50 MiB"
                )
            content = base64.b64decode(encoded, validate=True)
        elif source.startswith(("https://", "http://")):
            with client.stream("GET", source, follow_redirects=False) as response:
                if 300 <= response.status_code < 400:
                    raise ImageSourceError("Image reference redirects are not allowed")
                response.raise_for_status()
                content_buffer = bytearray()
                for chunk in response.iter_bytes():
                    if len(content_buffer) + len(chunk) >= MAX_IMAGE_BYTES:
                        raise _GPTToolError(
                            "image_input_too_large", "参考图片或蒙版必须小于 50 MiB"
                        )
                    content_buffer.extend(chunk)
                content = bytes(content_buffer)
        else:
            path = Path(source)
            if not path.is_absolute():
                path = settings.data_dir / "files" / path
            with path.open("rb") as file:
                content = file.read(MAX_IMAGE_BYTES)
        if len(content) >= MAX_IMAGE_BYTES:
            raise _GPTToolError(
                "image_input_too_large", "参考图片或蒙版必须小于 50 MiB"
            )
        if not content:
            raise _GPTToolError("invalid_image_input", "参考图片或蒙版为空")
        return content
    except ImageSourceError:
        raise _GPTToolError(
            "invalid_image_source", "图片来源必须是可访问的公网地址或图片 data URL"
        ) from None
    except _GPTToolError:
        raise
    except OSError, ValueError, binascii.Error, httpx2.HTTPError:
        raise _GPTToolError(
            "invalid_image_input", "参考图片或蒙版无效或无法读取"
        ) from None


def _inspect_image(
    content: bytes, error_code: str
) -> tuple[str, tuple[int, int], bool]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ValueError("Unsupported image format")
                result = (
                    image.format.lower(),
                    image.size,
                    "A" in image.getbands() or "transparency" in image.info,
                )
                image.verify()
                return result
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise _GPTToolError(
            error_code, "图片必须是有效的单帧 PNG、JPEG 或 WebP"
        ) from None


def handle_gpt_image_response(
    response: ImagesResponse,
    *,
    image_model: str,
    input_params: dict,
) -> ImageToolResponse:
    try:
        if not isinstance(response, ImagesResponse):
            raise ValueError("Invalid response type")
        response = ImagesResponse.model_validate(response.model_dump(warnings=False))
    except ValueError, TypeError:
        return _failure(
            image_model,
            "provider_invalid_response",
            "模型返回了无效响应",
            input_params=input_params,
        )
    usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    if not response.data:
        return _failure(
            image_model,
            "no_image_returned",
            "模型未返回图片",
            input_params=input_params,
            usage=usage,
        )
    if len(response.data) > input_params["n"]:
        return _failure(
            image_model,
            "provider_invalid_response",
            "模型返回了异常数量的图片",
            input_params=input_params,
            usage=usage,
        )
    images: list[dict] = []
    try:
        for item in response.data:
            encoded = item.b64_json
            if (
                not isinstance(encoded, str)
                or not encoded
                or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4
            ):
                raise _GPTToolError(
                    "provider_invalid_response", "模型返回了无效图片数据"
                )
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError, binascii.Error:
                raise _GPTToolError(
                    "provider_invalid_response", "模型返回了无效 base64 图片"
                ) from None
            if not content or len(content) >= MAX_IMAGE_BYTES:
                raise _GPTToolError(
                    "provider_invalid_response", "模型返回的图片为空或超出大小限制"
                )
            image_format, _, _ = _inspect_image(content, "provider_invalid_response")
            extension = "jpg" if image_format == "jpeg" else image_format
            try:
                uploaded = asyncio.run(
                    upload_image(
                        f"generated.{extension}", content, prefix="creative/gpt"
                    )
                )
                images.append(
                    uploaded.model_dump(
                        mode="json", exclude_unset=True, exclude_none=True
                    )
                )
            except Exception as error:
                logger.warning(
                    "GPT image upload failed: error_type=%s", type(error).__name__
                )
                raise _GPTToolError("image_upload_failed", "生成图片上传失败") from None
    except _GPTToolError as error:
        return _failure(
            image_model,
            error.code,
            error.message,
            input_params=input_params,
            usage=usage,
            images=images,
        )
    return ImageToolResponse(
        image_model=image_model,
        content="",
        success=True,
        images=images,
        usage=usage,
        input_params=input_params,
    )


def _image_create_with_gpt_image(
    prompt: str,
    *,
    image_model: str,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    provider: Literal["openai", "evolink"] = "openai",
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low",
    n: int = 1,
    size: str | None = None,
    background: Literal["auto", "opaque", "transparent"] | None = None,
    output_format: Literal["png", "jpeg", "webp"] | None = None,
    output_compression: int | None = None,
    moderation: Literal["auto", "low"] | None = None,
    safety_identifier: str | None = None,
    mask_url: str | None = None,
) -> ImageToolResponse:
    input_params: dict = {"provider": provider}
    started_at = time.perf_counter()
    base_url = None
    private_values = [
        value
        for value in (prompt, mask_url, safety_identifier)
        if isinstance(value, str)
    ]
    try:
        if provider not in {"openai", "evolink"}:
            raise _GPTToolError("unsupported_provider", "不支持当前 GPT 图片渠道")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
            raise _GPTToolError(
                "invalid_parameters", "prompt 必须是 1–32000 字符的非空文本"
            )
        if type(n) is not int or not 1 <= n <= 10:
            raise _GPTToolError("invalid_parameters", "n 必须是 1–10 的整数")
        allowed_quality = {"low", "medium", "high", "auto"}
        if image_model.startswith("gpt-image-2.5-"):
            allowed_quality.update({"xhigh", "max"})
        if quality not in allowed_quality:
            raise _GPTToolError("invalid_parameters", "当前模型不支持所选 quality")
        if (
            output_format not in {None, "png", "jpeg", "webp"}
            or background not in {None, "auto", "opaque", "transparent"}
            or moderation not in {None, "auto", "low"}
        ):
            raise _GPTToolError("invalid_parameters", "不支持当前图片输出或审核选项")
        effective_format = output_format or "png"
        if background == "transparent" and effective_format == "jpeg":
            raise _GPTToolError("invalid_parameters", "透明背景不能使用 JPEG 输出")
        if output_compression is not None and (
            type(output_compression) is not int
            or not 0 <= output_compression <= 100
            or effective_format not in {"jpeg", "webp"}
        ):
            raise _GPTToolError(
                "invalid_parameters",
                "output_compression 需要 JPEG/WebP 输出和 0–100 整数",
            )
        if safety_identifier is not None and (
            not isinstance(safety_identifier, str) or len(safety_identifier) > 128
        ):
            raise _GPTToolError(
                "invalid_parameters", "safety_identifier 最多允许 128 字符"
            )
        references = _sources(image_urls)
        private_values.extend(references)
        if mask_url is not None and (
            not references or not isinstance(mask_url, str) or not mask_url.strip()
        ):
            raise _GPTToolError("invalid_mask", "mask_url 必须配合至少一张参考图片")
        resolved_size = _resolve_size(size, aspect_ratio, image_size)
        input_params.update(
            {
                "operation": "edit" if references else "generate",
                "size": resolved_size,
                "quality": quality,
                "n": n,
                "output_format": effective_format,
                "reference_images": len(references),
                "mask": mask_url is not None,
            }
        )
        for name, value in (
            ("background", background),
            ("output_compression", output_compression),
            ("moderation", moderation),
        ):
            if value is not None:
                input_params[name] = value
        if provider == "evolink":
            if any(
                value is not None
                for value in (
                    size,
                    background,
                    output_format,
                    output_compression,
                    moderation,
                    safety_identifier,
                    mask_url,
                )
            ) or quality in {"xhigh", "max"}:
                raise _GPTToolError(
                    "unsupported_provider_parameter",
                    "Evolink 工具暂不支持新增 GPT 输出、蒙版、原生尺寸或扩展质量选项",
                )
            functions = {
                "gpt-image-2": gpt_evolink.image_create_with_gpt_image_2,
                "gpt-image-2.5-flare": gpt_evolink.image_create_with_gpt_image_2_5_flare,
                "gpt-image-2.5-sunburst": gpt_evolink.image_create_with_gpt_image_2_5_sunburst,
            }
            return functions[image_model](
                prompt,
                image_urls=image_urls,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                quality=cast(Any, quality),
                n=n,
            )
        config = settings.providers.openai
        if (
            config is None
            or not config.base_url
            or not config.api_key.get_secret_value()
        ):
            raise _GPTToolError("provider_unavailable", "OpenAI 图片渠道未配置")
        base_url = config.base_url
        private_values.append(config.api_key.get_secret_value())
        with httpx2.Client(
            proxy=settings.proxy_url, timeout=180, trust_env=False
        ) as http_client:
            files: list[tuple[str, bytes, str]] = []
            first_size = None
            for index, reference in enumerate(references):
                content = _read_source(reference, http_client)
                image_format, dimensions, _ = _inspect_image(
                    content, "invalid_image_input"
                )
                if index == 0:
                    first_size = dimensions
                    if mask_url is not None and image_format != "png":
                        with Image.open(BytesIO(content)) as image:
                            output = BytesIO()
                            image.convert(
                                "RGBA" if "A" in image.getbands() else "RGB"
                            ).save(output, format="PNG")
                            content = output.getvalue()
                        if len(content) >= MAX_IMAGE_BYTES:
                            raise _GPTToolError(
                                "image_input_too_large", "PNG 参考图片必须小于 50 MiB"
                            )
                        image_format = "png"
                files.append(
                    (
                        f"reference-{index}.{image_format}",
                        content,
                        "image/" + image_format,
                    )
                )
            mask = None
            if mask_url is not None:
                content = _read_source(mask_url, http_client)
                mask_format, dimensions, has_alpha = _inspect_image(
                    content, "invalid_mask"
                )
                if mask_format != "png" or not has_alpha or dimensions != first_size:
                    raise _GPTToolError(
                        "invalid_mask",
                        "蒙版必须是带 alpha 的 PNG，且与第一张参考图片尺寸一致",
                    )
                mask = ("mask.png", content, "image/png")
            options: dict[str, Any] = {
                "model": image_model,
                "prompt": prompt,
                "size": resolved_size,
                "quality": quality,
                "n": n,
                "output_format": effective_format,
            }
            for name, value in (
                ("background", background),
                ("output_compression", output_compression),
            ):
                if value is not None:
                    options[name] = value
            extra_body = {}
            if safety_identifier is not None:
                extra_body["safety_identifier"] = safety_identifier
            if moderation is not None:
                if references:
                    extra_body["moderation"] = moderation
                else:
                    options["moderation"] = moderation
            if extra_body:
                options["extra_body"] = extra_body
            with OpenAI(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                http_client=http_client,
                timeout=180,
                max_retries=0,
            ) as client:
                if files:
                    options["image"] = files
                    if mask is not None:
                        options["mask"] = mask
                    response = client.images.edit(**options)
                else:
                    response = client.images.generate(**options)
        return handle_gpt_image_response(
            cast(ImagesResponse, response),
            image_model=image_model,
            input_params=input_params,
        )
    except _GPTToolError as error:
        return _failure(
            image_model, error.code, error.message, input_params=input_params
        )
    except Exception as error:
        return _provider_failure(
            error,
            image_model=image_model,
            provider=provider,
            input_params=input_params,
            started_at=started_at,
            base_url=base_url,
            private_values=private_values,
        )


def image_create_with_gpt_image_2(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    provider: Literal["openai", "evolink"] = "openai",
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
    size: str | None = None,
    background: Literal["auto", "opaque", "transparent"] | None = None,
    output_format: Literal["png", "jpeg", "webp"] | None = None,
    output_compression: int | None = None,
    moderation: Literal["auto", "low"] | None = None,
    safety_identifier: str | None = None,
    mask_url: str | None = None,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
        quality=quality,
        n=n,
        size=size,
        background=background,
        output_format=output_format,
        output_compression=output_compression,
        moderation=moderation,
        safety_identifier=safety_identifier,
        mask_url=mask_url,
    )


def image_create_with_gpt_image_2_5_flare(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    provider: Literal["openai", "evolink"] = "openai",
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low",
    n: int = 1,
    size: str | None = None,
    background: Literal["auto", "opaque", "transparent"] | None = None,
    output_format: Literal["png", "jpeg", "webp"] | None = None,
    output_compression: int | None = None,
    moderation: Literal["auto", "low"] | None = None,
    safety_identifier: str | None = None,
    mask_url: str | None = None,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        # image_model="gpt-image-2.5-flare",
        image_model="gpt-image-2.5-flare-vip",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
        quality=quality,
        n=n,
        size=size,
        background=background,
        output_format=output_format,
        output_compression=output_compression,
        moderation=moderation,
        safety_identifier=safety_identifier,
        mask_url=mask_url,
    )


def image_create_with_gpt_image_2_5_sunburst(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    provider: Literal["openai", "evolink"] = "openai",
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low",
    n: int = 1,
    size: str | None = None,
    background: Literal["auto", "opaque", "transparent"] | None = None,
    output_format: Literal["png", "jpeg", "webp"] | None = None,
    output_compression: int | None = None,
    moderation: Literal["auto", "low"] | None = None,
    safety_identifier: str | None = None,
    mask_url: str | None = None,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        # image_model="gpt-image-2.5-sunburst",
        image_model="gpt-image-2.5-sunburst-vip",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
        quality=quality,
        n=n,
        size=size,
        background=background,
        output_format=output_format,
        output_compression=output_compression,
        moderation=moderation,
        safety_identifier=safety_identifier,
        mask_url=mask_url,
    )


def image_create_with_gpt_image_2_5(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    provider: Literal["openai", "evolink"] = "openai",
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low",
    n: int = 1,
    size: str | None = None,
    background: Literal["auto", "opaque", "transparent"] | None = None,
    output_format: Literal["png", "jpeg", "webp"] | None = None,
    output_compression: int | None = None,
    moderation: Literal["auto", "low"] | None = None,
    safety_identifier: str | None = None,
    mask_url: str | None = None,
) -> ImageToolResponse:
    """Compatibility entry point for GPT Image 2.5 Flare."""
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2.5-flare",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        provider=provider,
        quality=quality,
        n=n,
        size=size,
        background=background,
        output_format=output_format,
        output_compression=output_compression,
        moderation=moderation,
        safety_identifier=safety_identifier,
        mask_url=mask_url,
    )


if __name__ == "__main__":
    image = image_create_with_gpt_image_2(
        "35mm film photography with harsh convenience store fluorescent lighting mixed with colorful neon signs from outside, authentic film grain, high contrast, slight color cast, cinematic street editorial style, intimate medium shot, early 20s sexy Chinese female idol with ultra-realistic delicate refined Chinese features, seductive almond-shaped fox eyes with natural double eyelids, high nose bridge, small sharp V-shaped jawline, flawless porcelain skin with cool ivory undertone and visible specular highlights from fluorescent light, subtle skin texture and micro pores, natural dewy makeup with soft flush on cheeks, glossy natural pink lips slightly parted, subtle natural freckles across nose and cheeks, long dark brown hair in a messy high ponytail with many loose strands falling around face and neck, wearing an oversized white button-up shirt as the only top, unbuttoned at the top with deep cleavage and loosely tied at the waist, paired with a tiny black pleated mini skirt, barefoot in simple white slides, seductive casual leaning pose against the glass door of a 24-hour convenience store at late night, body slightly arched, one leg bent with foot resting against the door frame, the other leg straight, one hand holding a bottle of iced drink, the other hand lightly pulling the hem of her mini skirt, intensely seductive playful yet slightly vulnerable gaze straight at the viewer with soft doe eyes full of quiet temptation and teasing smile, bright cold fluorescent store light from inside mixed with pink and blue neon glow from outside signs, realistic reflections on glass door, blurred convenience store interior with shelves and snacks in background, authentic 35mm film color grading with harsh lighting and neon accents, extremely sharp yet soft skin rendering, natural hair strands, realistic fabric wrinkles and drape on the oversized shirt and mini skirt, no plastic skin, no digital over-sharpening, no airbrushing, no blemishes, no moles, no oily skin, no watermark, no text, authentic late-night convenience store atmosphere",
        quality="low",
    )
