import asyncio
from typing import Literal

import httpx2
from google.genai import types

from api.core import settings
from api.tools.types import ImageToolResponse
from api.utils.object_storage.aliyun_oss import upload_image

from api.tools.images.gemini import _create_client, _image_part


def image_inpaint_with_seedream(
    *,
    prompt: str,
    image_url: str,
    mask_url: str,
    image_size: Literal["2K", "4K"] | None = "2K",
) -> ImageToolResponse:
    """
    Args:
        prompt: The prompt for image inpainting.
        image_url: The original image URL or data URL.
        mask_url: The mask image URL or data URL.
        image_size: Target size ("2K" or "4K").
    """
    try:
        # Process image list (Seedream 4.5 expects a list)
        image_list = [image_url, mask_url]

        # Handle size
        base = 2
        match image_size:
            case "1K":
                base = 1
            case "2K":
                base = 2
            case "4K":
                base = 4
            case _:
                base = 2

        size = "4K" if base == 4 else "2K"

        config = settings.providers.volcengine
        if config is None or not config.api_key.get_secret_value():
            raise ValueError("Volcengine image provider is not configured")
        base_url = config.base_url.rstrip("/") + "/images/generations"
        api_key = config.api_key.get_secret_value()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        # Payload for inpainting
        # According to typical Doubao-Seedream API documentation for inpaint:
        # It often uses "image_list" and "region_list" or "mask"
        # Given the user says "image, mask 和 prompt", and references seedream4_5.py

        data = {
            "model": "doubao-seedream-4-5-251128",
            "prompt": prompt,
            "image": image_list,
            "response_format": "url",
            "size": size,
            "watermark": False,
        }

        response = httpx2.post(base_url, headers=headers, json=data, timeout=360)
        if response.status_code == 200:
            result = response.json()
            images: list[dict] = result.get("data", [])

            uploaded_urls = []
            for index, image in enumerate(images):
                response = httpx2.get(image.get("url"), timeout=180)
                response.raise_for_status()
                uploaded_image = asyncio.run(
                    upload_image(
                        "inpaint.png", response.content, prefix="creative/inpaint"
                    )
                )
                uploaded_urls.append(
                    uploaded_image.model_dump(
                        mode="json", exclude_none=True, exclude_unset=True
                    )
                )

            return ImageToolResponse(
                content=f"内容重绘完成, 共生成{len(uploaded_urls)}张图像",
                success=True,
                images=uploaded_urls,
            )
        else:
            try:
                error = response.json().get("error", {}).get("message", response.text)
            except:
                error = response.text
            return ImageToolResponse(
                content=f"内容重绘失败, 错误信息: {error}", success=False
            )
    except Exception as exc:
        return ImageToolResponse(
            content=f"工具调用失败, 无生成图像, 错误提示: {exc}", success=False
        )


def image_inpaint_with_gemini(
    prompt: str,
    image_url: str | None = None,
    mask_url: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = "2K",
) -> ImageToolResponse:
    try:
        image_parts = [_image_part(item) for item in [image_url, mask_url] if item]
        image_model = "gemini-2.5-flash-image"
        prompt = f"局部重绘, 图1是原图, 图2是mask. 重绘指令: {prompt}"
        with _create_client("google") as client:
            response = client.models.generate_content(
                model=image_model,
                contents=[prompt, *image_parts],
                config=types.GenerateContentConfig(
                    response_modalities=["Text", "Image"],
                ),
            )
        images = []
        for part in response.parts or []:
            if part.inline_data is None or not part.inline_data.data:
                continue
            uploaded_image = asyncio.run(
                upload_image(
                    "gemini.png", part.inline_data.data, prefix="creative/gemini"
                )
            )
            images.append(
                uploaded_image.model_dump(
                    mode="json", exclude_unset=True, exclude_none=True
                )
            )
        return ImageToolResponse(
            content=f"重绘完成, 共生成{len(images)}张图像, 图像信息:{images}",
            success=bool(images),
            images=images,
        )
    except Exception as exc:
        return ImageToolResponse(
            content=f"工具调用失败, 无生成图像, 错误提示: {exc}", success=False
        )
