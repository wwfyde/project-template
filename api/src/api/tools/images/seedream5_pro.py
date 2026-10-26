import asyncio
import base64
import io
import math
from pathlib import Path
from typing import Literal

import httpx2
import requests
from PIL import Image

from api.core import settings
from api.images.source_access import get_image_reference, guard_image_source
from api.utils.object_storage.aliyun_oss import upload_image
from api.tools.types import ImageToolResponse

IMAGE_MODEL = "doubao-seedream-5-0-pro-260628"
MAX_REFERENCE_IMAGES = 10
MIN_PIXELS = 1280 * 720
MAX_PIXELS = 2048 * 2048

SIZE_MAP = {
    "1K": {
        (1, 1): (1024, 1024),
        (4, 3): (1152, 864),
        (3, 4): (864, 1152),
        (16, 9): (1312, 736),
        (9, 16): (736, 1312),
        (3, 2): (1248, 832),
        (2, 3): (832, 1248),
        (21, 9): (1568, 672),
    },
    "2K": {
        (1, 1): (2048, 2048),
        (4, 3): (2304, 1728),
        (3, 4): (1728, 2304),
        (16, 9): (2848, 1600),
        (9, 16): (1600, 2848),
        (3, 2): (2496, 1664),
        (2, 3): (1664, 2496),
        (21, 9): (3136, 1344),
    },
}


def _normalize_image_size(image_size: str | None) -> Literal["1K", "2K"]:
    if image_size and image_size.upper() == "1K":
        return "1K"
    return "2K"


def _parse_ratio(aspect_ratio: str) -> tuple[int, int] | None:
    parts = (
        aspect_ratio.replace(":", "×").replace("x", "×").replace("X", "×").split("×")
    )
    if len(parts) != 2:
        return None
    try:
        width, height = [int(item.strip()) for item in parts]
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _normalize_custom_size(width: int, height: int) -> tuple[int, int]:
    pixels = width * height
    if pixels < MIN_PIXELS:
        scale = math.ceil(math.sqrt(MIN_PIXELS / pixels))
        width *= scale
        height *= scale
        pixels = width * height

    if pixels > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / pixels)
        width = max(15, int(width * scale))
        height = max(15, int(height * scale))

    return width, height


def _resolve_size(
    aspect_ratio: str | None,
    image_size: Literal["1K", "2K", "4K"] | None,
) -> tuple[str, Literal["1K", "2K"]]:
    normalized_size = _normalize_image_size(image_size)
    if not aspect_ratio or aspect_ratio == "auto":
        return normalized_size, normalized_size

    parsed_ratio = _parse_ratio(aspect_ratio)
    if not parsed_ratio:
        return normalized_size, normalized_size

    width, height = parsed_ratio
    mapped_size = SIZE_MAP[normalized_size].get((width, height))
    if mapped_size:
        width, height = mapped_size
    elif 1 / 16 <= width / height <= 16:
        width, height = _normalize_custom_size(width, height)
    else:
        width, height = SIZE_MAP[normalized_size][(1, 1)]

    width, height = _normalize_custom_size(width, height)
    return f"{width}x{height}", normalized_size


def image_create_with_seedream5_pro(
    *,
    prompt: str,
    image_urls: list[str] | str | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = "2K",
) -> ImageToolResponse:
    """

    Args:
        image_urls: Image URLs or local file names. Seedream 5.0 Pro supports up to 10 reference images.
        prompt: Required. The prompt for image generation. If you want to edit an image, please describe what you want
        to edit in the prompt.
        aspect_ratio:
        image_size:
    """
    size, normalized_image_size = "2K", "2K"

    try:
        size, normalized_image_size = _resolve_size(aspect_ratio, image_size)

        if isinstance(image_urls, str) and image_urls.startswith("data:"):
            image_list = [image_urls]
        elif isinstance(image_urls, str):
            image_list = [
                i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()
            ]
        elif image_urls is None:
            image_list = []
        else:
            image_list = image_urls

        if len(image_list) > MAX_REFERENCE_IMAGES:
            return ImageToolResponse(
                image_model=IMAGE_MODEL,
                content=f"工具调用失败, Seedream 5.0 Pro 最多支持传入 {MAX_REFERENCE_IMAGES} 张参考图",
                success=False,
                input_params={"image_size": normalized_image_size, "size": size},
            )

        new_urls = []
        for item in image_list:
            guard_image_source(item)
            # 处理本地文件
            if item.startswith("data:") and ";base64," in item:
                new_urls.append(item)
            elif item.startswith("http"):
                # 判断图像大小
                reference_response = get_image_reference(item, timeout=180)
                reference_response.raise_for_status()
                file_bytes = reference_response.content
                print(f"原始图像大小: {len(file_bytes) / (1024 * 1024):.2f} MB")
                if len(file_bytes) > 20 * 1024 * 1024:
                    with Image.open(io.BytesIO(file_bytes)) as img:
                        img.thumbnail((1024, 1024))

                        has_alpha = "A" in img.getbands()

                        buf = io.BytesIO()
                        if has_alpha:
                            img.save(buf, format="PNG", optimize=True)
                            mime = "image/png"
                        else:
                            img = img.convert("RGB")
                            img.save(buf, format="JPEG", quality=85, optimize=True)
                            mime = "image/jpeg"

                        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        data_url = f"data:{mime};base64,{image_base64}"
                        new_urls.append(data_url)
                elif len(file_bytes) > 10 * 1024 * 1024:
                    new_urls.append(f"{item}?x-oss-process=image/resize,l_1024")
                else:
                    new_urls.append(item)
            else:
                local_file_path = Path(item)
                if not local_file_path.is_absolute():
                    local_file_path = settings.data_dir / "files" / local_file_path
                content = local_file_path.read_bytes()
                uploaded_image = asyncio.run(
                    upload_image(local_file_path.name, content, prefix="files")
                )
                new_urls.append(uploaded_image.url)

        image_list = new_urls

        provider_config = settings.providers.volcengine
        if provider_config is None or not provider_config.api_key.get_secret_value():
            raise ValueError("Volcengine image provider is not configured")
        base_url = provider_config.base_url.rstrip("/") + "/images/generations"
        api_key = provider_config.api_key.get_secret_value()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        print(f"{size=}")
        data = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "image": image_list,
            "response_format": "url",
            "size": size,
            "output_format": "png",
            "optimize_prompt_options": {"mode": "standard"},
            "watermark": False,
        }
        if not image_list:
            data.pop("image")

        response = httpx2.post(base_url, headers=headers, json=data, timeout=360)
        response.raise_for_status()
        result = response.json()
        images: list[dict] = result.get("data", [])
        usage = result.get("usage", {})

        uploaded_urls = []
        for _, image in enumerate(images):
            image_url = image.get("url")
            if not image_url:
                continue

            response = httpx2.get(image_url, timeout=180)

            response.raise_for_status()
            uploaded_image = asyncio.run(
                upload_image(
                    "seedream.png", response.content, prefix="creative/seedream"
                )
            )
            uploaded_urls.append(
                uploaded_image.model_dump(
                    mode="json", exclude_none=True, exclude_unset=True
                )
            )

        if not uploaded_urls:
            raise ValueError("Image provider returned no images")

        return ImageToolResponse(
            image_model=IMAGE_MODEL,
            content=f"图像生成完成, 共生成{len(uploaded_urls)}张图像",
            success=True,
            images=uploaded_urls,
            usage=usage,
            input_params={"image_size": normalized_image_size, "size": size},
        )
    except Exception:
        return ImageToolResponse(
            image_model=IMAGE_MODEL,
            content="图像生成或上传失败",
            error="image_tool_failed",
            images=[],
            success=False,
            input_params={"image_size": normalized_image_size, "size": size},
        )
