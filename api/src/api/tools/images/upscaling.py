import asyncio
from typing import Literal

import httpx2

from api.core import settings
from api.tools.types import ImageToolResponse
from api.utils.object_storage.aliyun_oss import upload_image

from api.tools.images.gemini_sync import image_create_with_gemini

base_prompt = "超高清细节增强，4K分辨率，保持原图构图与内容不变，提升纹理清晰度、边缘锐度与色彩饱和度，专业摄影级画质"
base_prompt = "超高清细节增强，4K分辨率，保持原图构图、色彩与内容完全不变，强化纹理清晰度、边缘锐度与微表面质感，消除压缩伪影，专业级画质修复"


def image_upscaling_with_seedream(
    *,
    prompt: str | None = None,
    image_url: str,
    image_size: Literal["2K", "4K"] | None = "4K",
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
        image_list = [image_url]

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
        final_prompt = f"{prompt} {base_prompt}"
        data = {
            "model": "doubao-seedream-4-5-251128",
            "prompt": final_prompt,
            "image": image_list,
            "response_format": "url",
            "size": size,
            "watermark": False,
        }

        response = httpx2.post(base_url, headers=headers, json=data, timeout=360)
        if response.status_code == 200:
            result = response.json()
            images: list[dict] = result.get("data", [])
            usage = result.get("usage", {})

            uploaded_urls = []
            for index, image in enumerate(images):
                response = httpx2.get(image.get("url"), timeout=180)
                response.raise_for_status()
                uploaded_image = asyncio.run(
                    upload_image(
                        "upscaling.png", response.content, prefix="creative/seedream"
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
                input_params=dict(prompt=final_prompt),
                images=uploaded_urls,
                usage=usage,
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


def image_upscaling_with_gemini(
    prompt: str,
    image_url: str | None = None,
    image_size: Literal["2K", "4K"] | None = "4K",
) -> ImageToolResponse:
    return image_create_with_gemini(
        f"{prompt}  {base_prompt}",
        model="gemini-3.1-flash-image",
        image_urls=image_url,
        image_size=image_size,
    )


def test_upscaling() -> None:
    with open(settings.temp_dir / "IMG_0962.jpeg", "r+b") as f:
        data = f.read()
        uploaded_image = asyncio.run(upload_image("IMG_0962.jpeg", data, prefix="tmp"))
        resp = image_upscaling_with_seedream(
            image_url=uploaded_image.url, image_size="4K"
        )
        print(resp)
        print(resp.images)
