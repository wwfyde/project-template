import asyncio
import base64
import io
import math
from pathlib import Path
from typing import Literal, get_args

import httpx2
from arkruntime import AsyncArk
from PIL import Image

from api.core import settings
from api.images.source_access import get_image_reference_async, guard_image_source
from api.tools.types import ImageToolResponse, SeedreamImageModel
from api.utils.object_storage.aliyun_oss import upload_image

MAX_REFERENCE_IMAGES = 10
MIN_PIXELS = 1280 * 720
MAX_PIXELS = 4624220
LEGACY_MODELS = {"doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128"}

type ImageSize = Literal["1K", "1.5K", "2K", "4K"]

SIZE_MAP = {
    "1K": {
        (1, 1): (1024, 1024),
        (4, 3): (1152, 864),
        (3, 4): (864, 1152),
        (16, 9): (1424, 800),
        (9, 16): (800, 1424),
        (3, 2): (1248, 832),
        (2, 3): (832, 1248),
        (21, 9): (1568, 672),
    },
    "1.5K": {
        (1, 1): (1536, 1536),
        (4, 3): (1792, 1344),
        (3, 4): (1344, 1792),
        (16, 9): (2048, 1152),
        (9, 16): (1152, 2048),
        (3, 2): (1872, 1248),
        (2, 3): (1248, 1872),
        (21, 9): (2352, 1008),
    },
    "2K": {
        (1, 1): (2048, 2048),
        (4, 3): (2368, 1776),
        (3, 4): (1776, 2368),
        (16, 9): (2816, 1584),
        (9, 16): (1584, 2816),
        (3, 2): (2496, 1664),
        (2, 3): (1664, 2496),
        (21, 9): (3136, 1344),
    },
}

LEGACY_SIZE_MAP = {
    "1K": {
        **SIZE_MAP["1K"],
        (16, 9): (1280, 720),
        (9, 16): (720, 1280),
        (21, 9): (1512, 648),
    },
    "2K": {
        **SIZE_MAP["2K"],
        (4, 3): (2304, 1728),
        (3, 4): (1728, 2304),
        (16, 9): (2848, 1600),
        (9, 16): (1600, 2848),
    },
    "4K": {
        (1, 1): (4096, 4096),
        (4, 3): (4704, 3520),
        (3, 4): (3520, 4704),
        (16, 9): (5504, 3040),
        (9, 16): (3040, 5504),
        (3, 2): (4992, 3328),
        (2, 3): (3328, 4992),
        (21, 9): (6240, 2656),
    },
}


def _parse_ratio(aspect_ratio: str) -> tuple[int, int] | None:
    parts = aspect_ratio.replace(":", "×").replace("x", "×").replace("X", "×").split("×")
    if len(parts) != 2:
        return None
    try:
        width, height = [int(item.strip()) for item in parts]
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _normalize_custom_size(
    width: int,
    height: int,
    *,
    minimum: int = MIN_PIXELS,
    maximum: int = MAX_PIXELS,
) -> tuple[int, int]:
    pixels = width * height
    if pixels < minimum:
        scale = math.sqrt(minimum / pixels)
        width, height = math.ceil(width * scale), math.ceil(height * scale)
    elif pixels > maximum:
        scale = math.sqrt(maximum / pixels)
        width, height = int(width * scale), int(height * scale)
        # Flooring the short side can otherwise push an extreme ratio past 16:1.
        width, height = min(width, height * 16), min(height, width * 16)

    return width, height


def _resolve_size(
    aspect_ratio: str | None,
    image_size: ImageSize | None,
    model: SeedreamImageModel = "doubao-seedream-5-5-261028",
) -> str:
    normalized_size = image_size.upper() if image_size else "2K"
    size_map = LEGACY_SIZE_MAP if model in LEGACY_MODELS else SIZE_MAP
    if normalized_size not in size_map or (
        model == "doubao-seedream-4-5-251128" and normalized_size == "1K"
    ):
        raise ValueError("Unsupported image size for the selected model")
    if not aspect_ratio or aspect_ratio == "auto":
        return normalized_size

    parsed_ratio = _parse_ratio(aspect_ratio)
    if not parsed_ratio:
        return normalized_size

    width, height = parsed_ratio
    mapped_size = size_map[normalized_size].get((width, height))
    if mapped_size:
        width, height = mapped_size
    elif not 1 / 16 <= width / height <= 16:
        width, height = size_map[normalized_size][(1, 1)]

    width, height = _normalize_custom_size(
        width,
        height,
        minimum=3686400 if model == "doubao-seedream-4-5-251128" else MIN_PIXELS,
        maximum=4096 * 4096 if model in LEGACY_MODELS else MAX_PIXELS,
    )
    return f"{width}x{height}"


def _resize_reference(content: bytes) -> str:
    with Image.open(io.BytesIO(content)) as image:
        image.thumbnail((1024, 1024))
        output = io.BytesIO()
        if "A" in image.getbands():
            image.save(output, format="PNG", optimize=True)
            mime = "image/png"
        else:
            image.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
            mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(output.getvalue()).decode('ascii')}"


async def _prepare_reference(source: str, client: httpx2.AsyncClient) -> str:
    await asyncio.to_thread(guard_image_source, source)
    if source.startswith("data:") and ";base64," in source:
        return source
    if source.startswith(("http://", "https://")):
        response = await get_image_reference_async(source, client=client)
        response.raise_for_status()
        if len(response.content) > 20 * 1024 * 1024:
            return await asyncio.to_thread(_resize_reference, response.content)
        return source

    path = Path(source)
    if not path.is_absolute():
        path = settings.data_dir / "files" / path
    content = await asyncio.to_thread(path.read_bytes)
    uploaded = await upload_image(path.name, content, prefix="files")
    return uploaded.url


async def image_create_with_seedream(
    *,
    prompt: str,
    image: list[str] | str | None = None,
    aspect_ratio: str | None = None,
    image_size: ImageSize | None = "2K",
    model: SeedreamImageModel = "doubao-seedream-5-5-261028",
) -> ImageToolResponse:
    """Generate and upload images asynchronously using the Ark runtime SDK.

    Seedream 5.5 / 5.0 Pro / Flash accept 1K, 1.5K and 2K, and up to ten
    references. Seedream 4.0 / 4.5 also support 4K and up to fourteen references.
    Local paths are supported for direct Python calls only.
    """
    try:
        if model not in get_args(SeedreamImageModel.__value__):
            raise ValueError("Unsupported Seedream model")
        size = _resolve_size(aspect_ratio, image_size, model)
        config = settings.providers.volcengine
        if config is None or not config.api_key.get_secret_value():
            raise ValueError("Volcengine image provider is not configured")

        if isinstance(image, str) and image.startswith("data:"):
            image_list = [image]
        elif isinstance(image, str):
            image_list = [i.strip() for i in image.replace("，", ",").split(",") if i.strip()]
        elif image is None:
            image_list = []
        else:
            image_list = image

        maximum = 14 if model in LEGACY_MODELS else MAX_REFERENCE_IMAGES
        if len(image_list) > maximum:
            return ImageToolResponse(
                image_model=model,
                content=f"工具调用失败, 当前 Seedream 模型最多支持传入 {maximum} 张参考图",
                success=False,
                error="too_many_images",
                images=[],
            )

        uploaded_urls = []
        async with httpx2.AsyncClient(timeout=180, follow_redirects=True) as http_client:
            references = [await _prepare_reference(item, http_client) for item in image_list]
            async with AsyncArk.volc(
                api_key=config.api_key.get_secret_value(),
                base_url=config.base_url,
                timeout=360,
                max_retries=0,
            ) as client:
                result = await client.images.generate(
                    model=model,
                    prompt=prompt,
                    image=references or None,
                    size=size,
                    extra_body={
                        "response_format": "url",
                        "output_format": "jpeg" if model in LEGACY_MODELS else "png",
                        "optimize_prompt_options": {"mode": "standard"},
                    },
                    watermark=False,
                    stream=False,
                )
            usage = (
                result.usage.model_dump(mode="json", exclude_none=True)
                if result.usage is not None
                else {}
            )
            for generated in result.data or []:
                if generated.error is not None or not generated.url:
                    raise ValueError("Image provider returned an invalid image")
                response = await http_client.get(generated.url)
                response.raise_for_status()
                filename = "seedream.jpg" if model in LEGACY_MODELS else "seedream.png"
                uploaded_image = await upload_image(
                    filename, response.content, prefix="creative/seedream"
                )
                uploaded_urls.append(
                    uploaded_image.model_dump(mode="json", exclude_none=True, exclude_unset=True)
                )

        if not uploaded_urls:
            raise ValueError("Image provider returned no images")

        return ImageToolResponse(
            image_model=model,
            content=f"图像生成完成, 共生成{len(uploaded_urls)}张图像",
            success=True,
            images=uploaded_urls,
            usage=usage,
        )
    except Exception:
        return ImageToolResponse(
            image_model=model,
            content="图像生成或上传失败",
            error="image_tool_failed",
            images=[],
            success=False,
        )
