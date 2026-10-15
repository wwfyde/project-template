import io
from io import BytesIO
from typing import Literal

import httpx2
import requests
import uuid_utils as uuid
from PIL import Image
from google import genai
from google.genai import types

from api.core import settings, upload_image
from api.lib.image import parse_data_url_to_bytes, upload_image
from api.tools.types import ImageInfo, ImageToolResponse


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

    base_url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    api_key = settings.providers.ark.api_key

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

    try:
        response = httpx2.post(base_url, headers=headers, json=data, timeout=360)
        if response.status_code == 200:
            result = response.json()
            images: list[dict] = result.get("data", [])

            uploaded_urls = []
            for index, image in enumerate(images):
                response = httpx2.get(image.get("url"), timeout=180)
                content = response.content
                pil = Image.open(BytesIO(content))
                img_format = pil.format.lower() or "png"
                id = str(uuid.uuid7())
                filename = f"{id}.{img_format.replace('jpeg', 'jpg')}"
                image_url = upload_image(filename, data=content, prefix="creative/inpaint", rename=False)
                width, height = pil.size

                uploaded_urls.append(
                    ImageInfo(
                        url=image_url,
                        width=width,
                        height=height,
                        id=id,
                        filename=filename,
                        mime_type=f"image/{img_format}",
                        content=f"{image_url}",
                    ).model_dump(exclude_none=True, exclude_unset=True)
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
            return ImageToolResponse(content=f"内容重绘失败, 错误信息: {error}", success=False)

    except Exception as exc:
        return ImageToolResponse(content=f"工具调用失败, 无生成图像, 错误提示: {exc}", success=False)


api_key = settings.providers.gemini.api_key

http_options = types.HttpOptions(
    client_args={"proxy": settings.proxy_url},
    async_client_args={"proxy": settings.proxy_url},
)
client = genai.Client(api_key=api_key, http_options=http_options)


def image_inpaint_with_gemini(
        prompt: str,
        image_url: str | None = None,
        mask_url: str | None = None,
        image_size: Literal["1K", "2K", "4K"] | None = "2K",
) -> ImageToolResponse:
    new_urls = []
    image_list = [image_url, mask_url]
    for item in image_list:
        # 处理本地文件
        if item.startswith("data:") and "base64" in item:
            image_bytes = parse_data_url_to_bytes(item)
            new_urls.append(image_bytes)
        elif item.startswith("http"):
            content = requests.get(item).content
            new_urls.append(content)
        # 绝对路径
        elif item.startswith("/"):
            pass

    image_list = new_urls

    image_pils = []
    for image in image_list:
        image_bytes = BytesIO(image)
        image_pil = Image.open(image_bytes)
        image_pils.append(image_pil)
    image_model = "gemini-2.5-flash-image"  # "gemini-3-pro-image-preview"
    prompt = f"局部重绘, 图1是原图, 图2是mask. 重绘指令: {prompt}"
    response = client.models.generate_content(
        model=image_model,
        contents=[prompt, *image_pils],
        config=types.GenerateContentConfig(
            # response_modalities=["IMAGE"],
            response_modalities=["Text", "Image"],
        ),
    )
    print(f"使用生图模型: {image_model}")
    image_parts = [part for part in response.parts if part.inline_data]
    images = []
    for image_part in image_parts:
        image_bytes = image_part.inline_data.data
        mime_type = image_part.inline_data.mime_type
        extension = mime_type.split("/")[-1].replace("jpeg", "jpg")
        # print(f"Image format: {format}")
        id = str(uuid.uuid7())
        filename = f"{id}.{extension}"
        image_url = upload_image(filename, image_bytes, prefix="creative/gemini", rename=False)
        pil_image = Image.open(io.BytesIO(image_bytes))
        width, height = pil_image.size
        images.append(
            ImageInfo(
                id=id,
                url=image_url,
                mime_type=mime_type,  # noqa
                filename=filename,
                width=width,
                height=height,
            ).model_dump(exclude_unset=True, exclude_none=True)
        )

    return ImageToolResponse(
        content=f"重绘完成, 共生成{len(images)}张图像, 图像信息:{images}",
        success=True,
        images=images,
    )
