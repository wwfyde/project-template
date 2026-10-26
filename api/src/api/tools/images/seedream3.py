import asyncio
import base64
import math
import time
from pathlib import Path
from typing import Literal

import httpx2

from api.core import settings
from api.utils.object_storage.aliyun_oss import upload_image
from api.tools.types import ImageToolResponse
from api.tools.volcengine import (
    VISUAL_BASE_URL,
    AsyncResultRequest,
    ImageEditRequest,
    ImgPortraitRequest,
    Params,
    SeedreamVisionServiceIdentity,
    Txt2ImgRequest,
    create_volc_header,
    get_query_string,
    serialize_body,
)

IMAGE_MODEL = "seedream-3.0"
SYNC_QUERY_PARAMS = {"Action": "CVProcess", "Version": "2022-08-31"}
ASYNC_SUBMIT_QUERY_PARAMS = {
    "Action": "CVSync2AsyncSubmitTask",
    "Version": "2022-08-31",
}
ASYNC_RESULT_QUERY_PARAMS = {"Action": "CVSync2AsyncGetResult", "Version": "2022-08-31"}
ASYNC_POLL_INTERVAL_SECONDS = 1.0
ASYNC_POLL_TIMEOUT_SECONDS = 180.0
MIN_DIMENSION = 512
MAX_DIMENSION = 2048
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION

Seedream3Mode = Literal["auto", "text_to_image", "instruction_edit", "portrait"]

RECOMMENDED_2K_SIZES = {
    (1, 1): (1328, 1328),
    (4, 3): (1472, 1104),
    (3, 4): (1104, 1472),
    (3, 2): (1584, 1056),
    (2, 3): (1056, 1584),
    (16, 9): (1664, 936),
    (9, 16): (936, 1664),
    (21, 9): (2016, 864),
}


def _parse_aspect_ratio(aspect_ratio: str | None) -> tuple[int, int] | None:
    if not aspect_ratio or aspect_ratio.lower() == "auto":
        return None
    parts = (
        aspect_ratio.replace(":", "×").replace("x", "×").replace("X", "×").split("×")
    )
    if len(parts) != 2:
        return None
    try:
        width, height = (int(item.strip()) for item in parts)
    except ValueError:
        return None
    if width <= 0 or height <= 0 or not 1 / 16 <= width / height <= 16:
        return None
    return width, height


def _round_to_multiple(value: float, multiple: int = 16) -> int:
    return max(MIN_DIMENSION, min(MAX_DIMENSION, round(value / multiple) * multiple))


def _constrain_dimensions(width: int, height: int) -> tuple[int, int]:
    pixels = width * height
    scale = min(
        1,
        MAX_DIMENSION / width,
        MAX_DIMENSION / height,
        math.sqrt((MAX_PIXELS - 1) / pixels),
    )
    constrained_width = max(
        MIN_DIMENSION, min(MAX_DIMENSION, math.floor(width * scale / 16) * 16)
    )
    constrained_height = max(
        MIN_DIMENSION, min(MAX_DIMENSION, math.floor(height * scale / 16) * 16)
    )

    while constrained_width * constrained_height >= MAX_PIXELS:
        if constrained_width >= constrained_height:
            constrained_width -= 16
        else:
            constrained_height -= 16

    return constrained_width, constrained_height


def _fit_dimensions(width: int, height: int, target_pixels: int) -> tuple[int, int]:
    ratio = width / height
    fitted_width = math.sqrt(target_pixels * ratio)
    fitted_height = math.sqrt(target_pixels / ratio)
    return _round_to_multiple(fitted_width), _round_to_multiple(fitted_height)


def _resolve_dimensions(
    aspect_ratio: str | None, image_size: str | None
) -> tuple[int, int, str]:
    normalized_size = "1K" if image_size and image_size.upper() == "1K" else "2K"
    parsed_ratio = _parse_aspect_ratio(aspect_ratio) or (1, 1)

    if normalized_size == "2K" and parsed_ratio in RECOMMENDED_2K_SIZES:
        width, height = RECOMMENDED_2K_SIZES[parsed_ratio]
    elif parsed_ratio[0] >= 512 and parsed_ratio[1] >= 512:
        width, height = parsed_ratio
        pixels = width * height
        if width > MAX_DIMENSION or height > MAX_DIMENSION or pixels >= MAX_PIXELS:
            width, height = _constrain_dimensions(width, height)
    else:
        target_pixels = 1328 * 1328 if normalized_size == "2K" else 1024 * 1024
        width, height = _fit_dimensions(*parsed_ratio, target_pixels)

    return width, height, normalized_size


def _normalize_image_inputs(image_urls: list[str] | str | None) -> list[str]:
    if isinstance(image_urls, str) and image_urls.startswith("data:"):
        return [image_urls]
    if isinstance(image_urls, str):
        return [
            item.strip()
            for item in image_urls.replace("，", ",").split(",")
            if item.strip()
        ]
    return [item.strip() for item in image_urls or [] if item and item.strip()]


def _decode_data_url(data_url: str) -> bytes:
    try:
        _, encoded = data_url.split("base64,", maxsplit=1)
        return base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError("无效的图片 data URL") from exc


def _read_local_image(image: str) -> tuple[str, bytes]:
    path = Path(image)
    if not path.is_absolute():
        path = settings.data_dir / "files" / image
    if not path.is_file():
        raise ValueError(f"找不到本地图片: {image}")
    return path.name, path.read_bytes()


def _upload_portrait_input(image: str) -> str:
    if image.startswith(("http://", "https://")):
        return image

    if image.startswith("data:") and "base64," in image:
        content = _decode_data_url(image)
        filename = "portrait.png"
    else:
        filename, content = _read_local_image(image)

    uploaded_image = asyncio.run(
        upload_image(filename, content, prefix="files/seedream3")
    )
    return uploaded_image.url


def _prepare_instruction_input(image: str) -> tuple[list[str] | None, list[str] | None]:
    if image.startswith(("http://", "https://")):
        return [image], None
    if image.startswith("data:") and "base64," in image:
        return None, [base64.b64encode(_decode_data_url(image)).decode("utf-8")]

    _, content = _read_local_image(image)
    return None, [base64.b64encode(content).decode("utf-8")]


def _credentials() -> tuple[str, str, str]:
    jimeng = getattr(getattr(settings, "solutions", None), "jimeng", None)
    if not jimeng or not jimeng.access_key or not jimeng.secret_key:
        raise ValueError(
            "请配置 solutions.jimeng.access_key 和 solutions.jimeng.secret_key"
        )
    return jimeng.access_key, jimeng.secret_key, jimeng.base_url or VISUAL_BASE_URL


def _post_volcengine(body: dict, query_params: dict[str, str]) -> dict:
    access_key, secret_key, base_url = _credentials()
    params = Params(
        access_key=access_key,
        secret_key=secret_key,
        base_url=base_url,
        body=body,
        query_params=query_params,
    )
    payload = serialize_body(body)
    query_string = get_query_string(query_params)
    response = httpx2.post(
        f"{base_url}?{query_string}",
        content=payload,
        headers=create_volc_header(params),
        timeout=180,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 10000:
        raise RuntimeError(
            f"火山引擎请求失败: code={result.get('code')}, message={result.get('message', 'Unknown error')}"
        )
    return result


def _run_async_task(body: dict, req_key: str) -> dict:
    submit_result = _post_volcengine(body, ASYNC_SUBMIT_QUERY_PARAMS)
    task_id = submit_result.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError("火山引擎异步任务未返回 task_id")

    req_json = serialize_body({"return_url": True, "logo_info": {"add_logo": False}})
    deadline = time.monotonic() + ASYNC_POLL_TIMEOUT_SECONDS
    last_status = "in_queue"

    while time.monotonic() < deadline:
        result_body = AsyncResultRequest(
            req_key=req_key, task_id=task_id, req_json=req_json
        ).model_dump(exclude_none=True)
        result = _post_volcengine(result_body, ASYNC_RESULT_QUERY_PARAMS)
        data = result.get("data", {})
        if data.get("image_urls") or data.get("binary_data_base64"):
            return data

        last_status = data.get("status", last_status)
        if last_status == "done":
            raise RuntimeError("火山引擎任务已结束，但没有返回图片")
        if last_status in {"not_found", "expired"}:
            raise RuntimeError(f"火山引擎异步任务状态异常: {last_status}")
        time.sleep(ASYNC_POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"等待火山引擎异步任务超时，最后状态: {last_status}")


def _image_info_from_bytes(content: bytes) -> dict:
    uploaded_image = asyncio.run(
        upload_image("seedream3.png", content, prefix="creative/seedream")
    )
    return uploaded_image.model_dump(mode="json", exclude_none=True, exclude_unset=True)


def _collect_images(data: dict) -> list[dict]:
    images = []
    for image_url in data.get("image_urls") or []:
        response = httpx2.get(image_url, timeout=180)
        response.raise_for_status()
        images.append(_image_info_from_bytes(response.content))
    for encoded_image in data.get("binary_data_base64") or []:
        if encoded_image:
            images.append(_image_info_from_bytes(base64.b64decode(encoded_image)))
    return images


def image_create_with_seedream3(
    *,
    prompt: str,
    image_urls: list[str] | str | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K"] | None = "2K",
    mode: Seedream3Mode = "auto",
) -> ImageToolResponse:
    """Generate or edit one image with Seedream 3.0 through Volcengine Visual APIs.

    With ``mode="auto"``, no input image selects text-to-image and one input
    image selects instruction editing. Portrait generation must be selected with
    ``mode="portrait"``.
    """

    input_images = _normalize_image_inputs(image_urls)
    resolved_mode: Seedream3Mode = (
        "instruction_edit" if mode == "auto" and input_images else mode
    )
    if resolved_mode == "auto":
        resolved_mode = "text_to_image"
    width, height, normalized_size = _resolve_dimensions(aspect_ratio, image_size)
    input_params = {
        "mode": resolved_mode,
        "image_size": normalized_size,
        "width": width,
        "height": height,
    }

    try:
        if resolved_mode == "text_to_image":
            if input_images:
                raise ValueError("文生图模式不能传入 image_urls")
            request = Txt2ImgRequest(
                prompt=prompt,
                width=width,
                height=height,
                return_url=True,
                logo_info={"add_logo": False},
            )
            result = _post_volcengine(
                request.model_dump(exclude_none=True), SYNC_QUERY_PARAMS
            )
            data = result.get("data", {})
            image_model = SeedreamVisionServiceIdentity.General.value
        elif resolved_mode == "instruction_edit":
            if len(input_images) != 1:
                raise ValueError("SeedEdit 3.0 指令编辑需且仅需一张输入图片")
            edit_urls, edit_base64 = _prepare_instruction_input(input_images[0])
            request = ImageEditRequest(
                image_urls=edit_urls,
                binary_data_base64=edit_base64,
                prompt=prompt,
            )
            image_model = SeedreamVisionServiceIdentity.ImageEdit.value
            data = _run_async_task(request.model_dump(exclude_none=True), image_model)
        elif resolved_mode == "portrait":
            if len(input_images) != 1:
                raise ValueError("Seedream 3.0 人像写真需且仅需一张输入图片")
            request = ImgPortraitRequest(
                image_input=_upload_portrait_input(input_images[0]),
                prompt=prompt or None,
                width=width,
                height=height,
            )
            image_model = SeedreamVisionServiceIdentity.Portrait.value
            data = _run_async_task(request.model_dump(exclude_none=True), image_model)
        else:
            raise ValueError(f"不支持的 Seedream 3.0 模式: {resolved_mode}")

        images = _collect_images(data)
        if not images:
            raise RuntimeError("火山引擎响应中没有可用图片")

        return ImageToolResponse(
            image_model=image_model,
            content=f"图像生成完成, 共生成{len(images)}张图像",
            success=True,
            images=images,
            usage={"generated_images": len(images)},
            input_params=input_params,
        )
    except Exception as exc:
        return ImageToolResponse(
            image_model=IMAGE_MODEL,
            content=f"工具调用失败, 无生成图像, 错误提示: {exc}",
            success=False,
            error=str(exc),
            input_params=input_params,
        )
