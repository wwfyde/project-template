import time
from io import BytesIO
from typing import Literal

import httpx2
import requests
import uuid_utils as uuid
from PIL import Image

from api.core import upload_image
from api.lib.config import settings
from api.lib.image import parse_data_url_to_bytes
from api.tools.types import ImageInfo, ImageToolResponse

url = "https://api.evolink.ai/v1/images/generations"
base_url = "https://api.evolink.ai"
api_key = settings.providers.evolink.api_key if settings.providers.evolink else None
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
    "1:1", "1:2", "2:1", "1:3", "3:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
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
        width, height = [int(float(item.strip())) for item in normalized.split(separator, maxsplit=1)]
    except (TypeError, ValueError):
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
        ideal_short_edge = long_edge / source_ratio if is_landscape else long_edge * source_ratio
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
            size_error = abs(max(output_width, output_height) - target_long_edge) / target_long_edge
            candidates.append((ratio_error * 1000 + size_error, output_width, output_height))

    if not candidates:
        return None

    _, output_width, output_height = min(candidates, key=lambda item: item[0])
    return f"{output_width}x{output_height}"


def normalize_size(size: str | None, resolution: Literal["1K", "2K", "4K"]) -> str | None:
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


def create_task(
        prompt: str,
        *,
        image_model: str = "gpt-image-2",
        image_urls: list[str] | None = None,
        quality: Literal["low", "medium", "high", "auto"] = "low",
        resolution: Literal["1K", "2K", "4K"] | None = "1K",
        size: AspectRatio | None = None,
        n: int = 1,
):
    if not api_key:
        raise ValueError(f"Evolink API key is required to use {image_model}")

    resolution = normalize_resolution(resolution)
    # size = normalize_size(size, resolution)
    if not size and image_urls:
        pass
        # image_list = (
        #     [i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()]
        #     if isinstance(image_urls, str)
        #     else image_urls
        # )
        # if image_list:
        #     image_dimensions = get_image_dimensions(image_list[0])
        #     if image_dimensions:
        #         size = calculate_custom_size(*image_dimensions, resolution=resolution)
    if not size:
        # size = calculate_custom_size(*DEFAULT_ASPECT_RATIO, resolution=resolution)
        pass
    payload = {
        "model": image_model,
        "prompt": prompt,
        "n": min(max(n, 1), 10),
        "quality": quality,
        "resolution": resolution,
    }
    if size:
        payload["size"] = size
    if image_urls:
        payload["image_urls"] = image_urls
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    print(response.json())
    print("任务创建完成")
    if response.status_code == 200:
        task_id = response.json()["id"]
        print(response.text)
        return task_id
    else:
        raise Exception(f"Failed to create task: {response.status_code} {response.json()}")


def get_task(task_id):
    """获取任务状态"""
    response = requests.get(
        f"{base_url}/v1/tasks/{task_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    """
    {
      "model": "gpt-image-2",
      "prompt": "A beautiful colorful sunset over the ocean",
      "n": 1,
      "quality": "low",
      "resolution": "1K",
      "size": "4:3"
    }
    """
    return response.json()


def wait_for_completion(task_id, timeout=300) -> list[str]:
    start_time = time.time()
    while time.time() - start_time < timeout:
        task = get_task(task_id)

        if task['status'] == 'completed':
            print(task)
            result = task['results']
            print(result)
            print(f"图像URL: {task['results'][0]}")
            return task['results']
        elif task['status'] == 'failed':
            raise Exception(f"任务失败: {task.get('error')}")
        else:
            print(f"任务状态: {task['status']}, 等待中...")

        time.sleep(5)

    raise TimeoutError("任务执行超时")


def image_create_with_gpt_image_2(
        prompt: str,
        *,
        image_urls: str | list | None = None,
        aspect_ratio: AspectRatio | str | None = None,
        image_size: Literal["1K", "2K", "4K"] | None = None,
        quality: Literal["low", "medium", "high", "auto"] = "low",
        n: int = 1,
):
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


def image_create_with_gpt_image_2_5(
        prompt: str,
        *,
        image_urls: str | list | None = None,
        aspect_ratio: AspectRatio | str | None = None,
        image_size: Literal["1K", "2K", "4K"] | None = None,
        quality: Literal["low", "medium", "high", "auto"] = "low",
        n: int = 1,
):
    return _image_create_with_gpt_image(
        prompt,
        image_model="gpt-image-2.5",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        quality=quality,
        n=n,
    )


def _image_create_with_gpt_image(
        prompt: str,
        *,
        image_model: str,
        image_urls: str | list | None = None,
        aspect_ratio: AspectRatio | str | None = None,
        image_size: Literal["1K", "2K", "4K"] | None = None,
        quality: Literal["low", "medium", "high", "auto"] = "low",
        n: int = 1,
):
    if isinstance(image_urls, str):
        image_urls = [i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()]
    elif image_urls is None:
        image_urls = []

    try:
        task_id = create_task(
            prompt,
            image_model=image_model,
            image_urls=image_urls, quality=quality,
            resolution=normalize_resolution(image_size),
            size=aspect_ratio,
            n=n,
        )
    except Exception as exc:
        return ImageToolResponse(
            image_model=image_model,
            content=f"生图任务创建失败: {exc}",
            success=False,
            images=[],
            usage=None
        )
    try:
        results = wait_for_completion(task_id, timeout=300)
    except TimeoutError as e:
        print(f"Error: {e}")
        return ImageToolResponse(
            image_model=image_model,
            content="超时",
            success=False,
            images=[],
            usage=None,
        )
    except Exception:
        return ImageToolResponse(
            image_model=image_model,
            content="出现不适内容, 请修改提示词",
            success=False,
            images=[],
            usage=None,
        )

    images = []
    text = ""
    for url in results:
        response = httpx2.get(url, timeout=180)
        image_bytes = response.content
        pil = Image.open(BytesIO(image_bytes))
        img_format = pil.format.lower() if pil.format else "png"
        id = str(uuid.uuid7())
        filename = f"{id}.{img_format.replace('jpeg', 'jpg')}"
        image_url = upload_image(filename, image_bytes, prefix="creative/gpt", rename=False)
        if image_url is None:
            continue
        width, height = pil.size
        images.append(
            ImageInfo(
                id=id,
                url=image_url,
                mime_type=f"image/{img_format}",  # noqa
                filename=filename,
                width=width,
                height=height,
                file_size=len(image_bytes) if image_bytes else None,
            ).model_dump(exclude_unset=True, exclude_none=True)
        )
    # usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    return ImageToolResponse(
        image_model=image_model,
        content=text or "",
        success=True,
        images=images,
        usage=None,
    )


if __name__ == "__main__":
    image = image_create_with_gpt_image_2(
        "A beautiful colorful sunset over the ocean",
        quality="low",
        aspect_ratio="1920x1088"
    )
    print(image)
