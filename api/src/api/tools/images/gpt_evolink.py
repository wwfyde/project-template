import asyncio
import time
from io import BytesIO
from typing import Literal
from urllib.parse import quote

import httpx2
import requests
from PIL import Image

from api.core import parse_data_url_to_bytes, settings
from api.tools.types import ImageToolResponse
from api.utils.object_storage.aliyun_oss import upload_image

SUPPORTED_ASPECT_RATIOS = {
    "1:1": (1, 1),
    "1:2": (1, 2),
    "2:1": (2, 1),
    "1:3": (1, 3),
    "3:1": (3, 1),
    "2:3": (2, 3),
    "3:2": (3, 2),
    "3:4": (3, 4),
    "4:3": (4, 3),
    "4:5": (4, 5),
    "5:4": (5, 4),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "21:9": (21, 9),
}
type AspectRatio = Literal[
    "1:1",
    "1:2",
    "2:1",
    "1:3",
    "3:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
]
SUPPORTED_RESOLUTIONS = {"1K", "2K", "4K"}
RESOLUTION_LONG_EDGES = {
    "1K": 1024,
    "2K": 2048,
    "4K": 3840,
}
MIN_EDGE = 16
MAX_EDGE = 3840
EDGE_MULTIPLE = 16
MAX_EDGE_RATIO = 3
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
DEFAULT_ASPECT_RATIO = (4, 3)


def normalize_resolution(resolution: str | None) -> Literal["1K", "2K", "4K"]:
    if not resolution:
        return "1K"

    normalized = resolution.upper()
    if normalized in {"1", "2", "4"}:
        normalized = f"{normalized}K"

    if normalized in SUPPORTED_RESOLUTIONS:
        return normalized  # type: ignore[return-value]

    return "1K"


def is_valid_gpt_size(width: int, height: int) -> bool:
    if width < MIN_EDGE or height < MIN_EDGE:
        return False
    if width > MAX_EDGE or height > MAX_EDGE:
        return False
    if width % EDGE_MULTIPLE != 0 or height % EDGE_MULTIPLE != 0:
        return False
    if max(width, height) / min(width, height) > MAX_EDGE_RATIO:
        return False
    pixels = width * height
    return MIN_PIXELS <= pixels <= MAX_PIXELS


def parse_size_ratio(size: str | None) -> tuple[int, int] | None:
    if not size:
        return None

    normalized = size.strip().replace("：", ":").replace("×", "x").replace("X", "x")
    separator = "x" if "x" in normalized else ":"
    if separator not in normalized:
        return None

    try:
        width, height = [
            int(float(item.strip())) for item in normalized.split(separator, maxsplit=1)
        ]
    except TypeError, ValueError:
        return None

    if width <= 0 or height <= 0:
        return None
    return width, height


def calculate_custom_size(
    width: int,
    height: int,
    resolution: Literal["1K", "2K", "4K"] = "1K",
) -> str | None:
    if width <= 0 or height <= 0:
        return None
    if max(width, height) / min(width, height) > MAX_EDGE_RATIO:
        return None

    source_ratio = width / height
    is_landscape = width >= height
    target_long_edge = RESOLUTION_LONG_EDGES[resolution]
    candidates: list[tuple[float, int, int]] = []

    for long_edge in range(EDGE_MULTIPLE, MAX_EDGE + EDGE_MULTIPLE, EDGE_MULTIPLE):
        ideal_short_edge = (
            long_edge / source_ratio if is_landscape else long_edge * source_ratio
        )
        short_edges = {
            max(MIN_EDGE, round(ideal_short_edge / EDGE_MULTIPLE) * EDGE_MULTIPLE),
            max(MIN_EDGE, int(ideal_short_edge // EDGE_MULTIPLE) * EDGE_MULTIPLE),
            max(MIN_EDGE, int(-(-ideal_short_edge // EDGE_MULTIPLE)) * EDGE_MULTIPLE),
        }
        for short_edge in short_edges:
            output_width, output_height = (
                (long_edge, short_edge) if is_landscape else (short_edge, long_edge)
            )
            if not is_valid_gpt_size(output_width, output_height):
                continue

            output_ratio = output_width / output_height
            ratio_error = abs(output_ratio - source_ratio) / source_ratio
            size_error = (
                abs(max(output_width, output_height) - target_long_edge)
                / target_long_edge
            )
            candidates.append(
                (ratio_error * 1000 + size_error, output_width, output_height)
            )

    if not candidates:
        return None

    _, output_width, output_height = min(candidates, key=lambda item: item[0])
    return f"{output_width}x{output_height}"


def normalize_size(
    size: str | None, resolution: Literal["1K", "2K", "4K"]
) -> str | None:
    ratio = parse_size_ratio(size)
    if not ratio:
        return None

    custom_size = calculate_custom_size(*ratio, resolution=resolution)
    if custom_size:
        return custom_size

    return calculate_custom_size(*DEFAULT_ASPECT_RATIO, resolution=resolution)


def get_image_dimensions(image_url: str) -> tuple[int, int] | None:
    try:
        if image_url.startswith("data:"):
            image_bytes = parse_data_url_to_bytes(image_url)
        elif image_url.startswith("http"):
            response = requests.get(image_url, timeout=60)
            response.raise_for_status()
            image_bytes = response.content
        elif image_url.startswith("/"):
            with open(image_url, "rb") as file:
                image_bytes = file.read()
        else:
            image_bytes = (settings.data_dir / "files" / image_url).read_bytes()

        with Image.open(BytesIO(image_bytes)) as image:
            return image.size
    except Exception as exc:
        print(f"读取首图尺寸失败: {exc}")
        return None


def normalize_image_urls(image_urls: str | list[str] | None) -> list[str]:
    if isinstance(image_urls, str):
        if image_urls.startswith("data:"):
            return [image_urls]
        return [
            item.strip()
            for item in image_urls.replace("，", ",").split(",")
            if item.strip()
        ]
    return list(image_urls or [])


def _configuration() -> tuple[str, str]:
    config = settings.providers.evolink
    if config is None or not config.api_key.get_secret_value():
        raise ValueError("Evolink image provider is not configured")
    return config.base_url.rstrip("/"), config.api_key.get_secret_value()


def create_task(
    prompt: str,
    *,
    image_model: str = "gpt-image-2",
    image_urls: list[str] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    resolution: Literal["1K", "2K", "4K"] | None = "1K",
    size: AspectRatio | str | None = None,
    n: int = 1,
) -> str:
    base_url, api_key = _configuration()
    if isinstance(n, bool) or not 1 <= n <= 10:
        raise ValueError("Image count must be between 1 and 10")
    payload = {
        "model": image_model,
        "prompt": prompt,
        "n": n,
        "quality": quality,
        "resolution": normalize_resolution(resolution),
    }
    if size:
        payload["size"] = size
    if image_urls:
        payload["image_urls"] = image_urls
    response = requests.post(
        base_url + "/images/generations",
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=180,
        proxies={"http": settings.proxy_url, "https": settings.proxy_url}
        if settings.proxy_url
        else None,
    )
    response.raise_for_status()
    return response.json()["id"]


def get_task(task_id: str) -> dict:
    """获取任务状态。"""
    base_url, api_key = _configuration()
    response = requests.get(
        f"{base_url}/tasks/{quote(task_id, safe='')}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
        proxies={"http": settings.proxy_url, "https": settings.proxy_url}
        if settings.proxy_url
        else None,
    )
    response.raise_for_status()
    return response.json()


def wait_for_completion(task_id: str, timeout: float = 300) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = get_task(task_id)
        if task["status"] == "completed":
            return task["results"]
        if task["status"] in {"failed", "cancelled", "canceled"}:
            raise RuntimeError("Image generation task failed")
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError("Image generation timed out")


def _image_create_with_gpt_image(
    prompt: str,
    *,
    image_model: str,
    image_urls: str | list[str] | None = None,
    aspect_ratio: AspectRatio | str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
) -> ImageToolResponse:
    try:
        task_id = create_task(
            prompt,
            image_model=image_model,
            image_urls=normalize_image_urls(image_urls),
            quality=quality,
            resolution=normalize_resolution(image_size),
            size=aspect_ratio,
            n=n,
        )
        results = wait_for_completion(task_id, timeout=300)
        images = []
        for url in results:
            response = httpx2.get(url, timeout=180, proxy=settings.proxy_url)
            response.raise_for_status()
            content = response.content
            with Image.open(BytesIO(content)) as image:
                extension = (image.format or "PNG").lower().replace("jpeg", "jpg")
            uploaded = asyncio.run(
                upload_image(f"generated.{extension}", content, prefix="creative/gpt")
            )
            images.append(uploaded.model_dump(exclude_unset=True, exclude_none=True))
        return ImageToolResponse(
            image_model=image_model,
            content="" if images else "模型未返回可用图片",
            success=bool(images),
            images=images,
        )
    except TimeoutError:
        return ImageToolResponse(
            image_model=image_model, content="图片生成超时", success=False, images=[]
        )
    except Exception:
        return ImageToolResponse(
            image_model=image_model,
            content="GPT 图片生成或上传失败",
            success=False,
            images=[],
        )


def image_create_with_gpt_image_2(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: AspectRatio | str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


def image_create_with_gpt_image_2_5_flare(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: AspectRatio | str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2.5-flare",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


def image_create_with_gpt_image_2_5_sunburst(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: AspectRatio | str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
) -> ImageToolResponse:
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2.5-sunburst",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


def image_create_with_gpt_image_2_5(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: AspectRatio | str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
    quality: Literal["low", "medium", "high", "auto"] = "low",
    n: int = 1,
) -> ImageToolResponse:
    """Compatibility entry point for GPT Image 2.5 Flare."""
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2.5-flare",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


if __name__ == "__main__":
    image = image_create_with_gpt_image_2(
        "A beautiful colorful sunset over the ocean",
        quality="low",
        aspect_ratio="1920x1088",
    )
    print(image)
