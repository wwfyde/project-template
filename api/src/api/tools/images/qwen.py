import asyncio
import http
import json
from http import HTTPStatus
from pathlib import Path
from typing import Literal

import httpx2
import requests
from api.core import settings
from api.utils.object_storage.aliyun_oss import upload_image
from api.tools.types import ImageToolResponse
from dashscope import ImageSynthesis, MultiModalConversation


def _api_key() -> str:
    config = settings.providers.dashscope
    if config is None or not config.api_key.get_secret_value():
        raise ValueError("DashScope image provider is not configured")
    return config.api_key.get_secret_value()


def image_edit_with_qwen(
    *,
    prompt: str,
    image_urls: list[str] | str | None = None,
    negative_prompt: str | None = None,
) -> ImageToolResponse:
    try:
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
            # 处理本地文件
            if item.startswith("data:") and ";base64," in item:
                new_urls.append(item)
            elif item.startswith("http"):
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
        image_content = [{"image": image_url} for image_url in image_list]
        content = [{"text": prompt}, *image_content]

        messages = [
            {
                "role": "user",
                "content": content,
            }
        ]

        resp = MultiModalConversation.call(
            api_key=_api_key(),
            model="qwen-image-edit",
            messages=messages,
            result_format="message",
            stream=False,
            watermark=False,
            negative_prompt=negative_prompt,
        )

        if resp.status_code == http.HTTPStatus.OK:
            contents: dict = resp.output.choices[0].message.get("content", [])

            temp_image_url = contents[0].get("image", "")
            image_response = httpx2.get(temp_image_url, timeout=60)
            image_response.raise_for_status()
            uploaded_image = asyncio.run(
                upload_image("qwen.png", image_response.content, prefix="creative/qwen")
            )
            image_info = uploaded_image.model_dump(
                mode="json", exclude_unset=True, exclude_none=True
            )
            return ImageToolResponse(
                content=json.dumps(image_info, ensure_ascii=False),
                success=True,
                images=[image_info],
                image_model="qwen-image-1",
            )
        else:
            return ImageToolResponse(
                content=f"同步调用失败, status_code: {resp.status_code}, code: {resp.code}, message: {resp.message}",
                success=False,
                image_model="qwen-image-1",
            )

    except Exception as e:
        return ImageToolResponse(content=f"工具调用失败, 错误提示: {e}", success=False)


def image_generate_with_qwen(
    *,
    prompt: str,
    negative_prompt: str | None = None,
    aspect_ratio: Literal["1:1", "4:3", "3:4", "16:9"] = None,
) -> ImageToolResponse:
    try:
        aspect_ratio = aspect_ratio.replace("×", ":") if aspect_ratio else None
        if aspect_ratio == "1:1":
            width = 1328
            height = 1328
        elif aspect_ratio == "4:3":
            width = 1472
            height = 1140
        elif aspect_ratio == "3:4":
            width = 1140
            height = 1472
        elif aspect_ratio == "16:9":
            width = 1664
            height = 928
        elif aspect_ratio == "9:16":
            width = 928
            height = 1664
        else:
            width = 1328
            height = 1328

        resp = ImageSynthesis.call(
            api_key=_api_key(),
            model="qwen-image",
            prompt=prompt,
            n=1,
            size=f"{width}*{height}",
            negative_prompt=negative_prompt,
        )
        urls = []
        images = []
        if resp.status_code == HTTPStatus.OK:
            # 在当前目录下保存图片
            for result in resp.output.results:
                image_response = requests.get(result.url, timeout=60)
                image_response.raise_for_status()
                uploaded_image = asyncio.run(
                    upload_image(
                        "qwen.png", image_response.content, prefix="creative/qwen"
                    )
                )
                urls.append(uploaded_image.url)
                images.append(
                    uploaded_image.model_dump(
                        mode="json", exclude_unset=True, exclude_none=True
                    )
                )

        else:
            return ImageToolResponse(
                content=f"同步调用失败, status_code: {resp.status_code}, code: {resp.code}, message: {resp.message}",
                success=False,
            )
        url = urls[0] if len(urls) > 0 else ""
        image_info: dict | None = images[0] if len(images) > 0 else None

        # image_info = dict(url=url, mime_type=f"image/{img_format}")
        return ImageToolResponse(
            content=json.dumps(image_info, ensure_ascii=False),
            success=True,
            images=[image_info] if image_info else None,
            image_model="qwen-image-1",
        )
    except Exception as error:
        return ImageToolResponse(
            content=f"工具调用失败, 错误提示: {error}", success=False
        )


if __name__ == "__main__":
    resp = image_generate_with_qwen(prompt="生成一碗牛肉面")
    print(resp)
    # resp = image_edit_with_qwen(
    #     prompt="将图像改为卡通风格",
    #     image_urls=["https://cdn.fullspeed.cn/seedream/019b0122-9129-7520-b479-93dea16aea0a.jpg"],
    # )
    # print(resp)
    pass
