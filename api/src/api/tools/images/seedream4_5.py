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


def image_create_with_seedream4_5(
    *,
    prompt: str,
    image_urls: list[str] | str | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["2K", "4K"] | None = "2K",
) -> ImageToolResponse:
    """

    Args:
        image_urls: Search terms to look for
        prompt: Required. The prompt for image generation. If you want to edit an image, please describe what you want
                to edit in the prompt.
        aspect_ratio:
        image_size:
    """
    try:
        # TODO: 考虑使用字符串逗号隔开, 还是list

        # 基于image_size确定缩放倍率
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
        if aspect_ratio:
            width, height = [
                int(item)
                for item in aspect_ratio.replace(":", "×").replace("x", "×").split("×")
            ]

            if int(width) == 1 and int(height) == 1:
                width, height = 1024 * base, 1024 * base
            elif int(width) == 16 and int(height) == 9:
                width, height = 1280 * base, 720 * base
            elif int(width) == 9 and int(height) == 16:
                width, height = 720 * base, 1280 * base
            elif int(width) == 4 and int(height) == 3:
                width, height = 1125 * base, 864 * base
            elif int(width) == 3 and int(height) == 4:
                width, height = 864 * base, 1125 * base
            elif int(width) == 3 and int(height) == 2:
                width, height = 1248 * base, 832 * base
            elif int(width) == 2 and int(height) == 3:
                width, height = 832 * base, 1248 * base
            elif int(width) == 21 and int(height) == 9:
                width, height = 1512 * base, 648 * base

            # 处理自定义分辨率逻辑
            elif 1 / 16 <= width / height <= 16:
                if width * height < 3686400:
                    # 自定义缩放比例
                    scale = math.ceil(math.sqrt(3686400 // (width * height)))
                    width, height = (
                        int(width) * scale * base // 2,
                        int(height) * scale * base // 2,
                    )
                else:
                    width, height = int(width), int(height)
            # 图像分辨率不对 默认 1: 1
            else:
                width, height = 2048, 2048  # 默认值
            size = f"{width}x{height}"
        else:
            size = "4K" if base == 4 else "2K"
        # seed = random.randrange(-1, 2**31 -1)
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
        use_stream = False
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        data = {
            "model": "doubao-seedream-4-5-251128",
            "prompt": prompt,
            "image": image_list,
            "sequential_image_generation": "auto",
            "sequential_image_generation_options": {"max_images": 15},
            "response_format": "url",
            "size": size,
            "stream": use_stream,
            "optimize_prompt_options": {
                "mode": "standard"
            },  # support standard and fast mode
            # "seed": seed or -1,
            "watermark": False,
        }
        if not image_list:
            data.pop("image")

        if use_stream:
            with httpx2.Client() as client:
                with client.stream(
                    "POST", base_url, json=data, headers=headers, timeout=180
                ) as response:
                    for line in response.iter_lines():
                        if line:
                            # print(line)
                            pass
            return ImageToolResponse(
                image_model="doubao-seedream-4-5-251128",
                content="暂不支持该参数 use_stream ",
                success=False,
            )
        else:
            response = httpx2.post(base_url, headers=headers, json=data, timeout=360)
            response.raise_for_status()
            result = response.json()
            images: list[dict] = result.get("data", [])
            usage = result.get("usage", {})

            uploaded_urls = []
            for _, image in enumerate(images):
                response = httpx2.get(image.get("url"), timeout=180)

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
                image_model="doubao-seedream-4-5-251128",
                content=f"图像生成完成, 共生成{len(uploaded_urls)}张图像",
                success=True,
                images=uploaded_urls,
                usage=usage,
            )
    except Exception:
        return ImageToolResponse(
            image_model="doubao-seedream-4-5-251128",
            content="图像生成或上传失败",
            error="image_tool_failed",
            images=[],
            success=False,
        )


if __name__ == "__main__":
    resp = image_create_with_seedream4_5(
        prompt="生成一只可爱的猫咪", aspect_ratio="3:4"
    )
    print(resp)
