import io
import logging
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import requests
import uuid_utils as uuid
from google import genai
from google.genai import errors, types
from google.genai.types import GenerateContentResponse, ThinkingLevel
from PIL import Image

from api.core import settings, upload_image
from api.lib.image import parse_data_url_to_bytes
from api.tools.types import ImageInfo, ImageToolResponse

gemini_config = settings.providers.google
api_key = gemini_config.api_key
vertex_api_key = gemini_config.vertex_api_key

# logging.basicConfig(level=logging.DEBUG)

# 过滤掉其他模块的噪音，专注网络层
# logging.getLogger("httpcore").setLevel(logging.DEBUG)
# logging.getLogger("httpx2").setLevel(logging.DEBUG)

use_vertexai = settings.providers.google.use_vertexai
use_image_url = True

http_options = types.HttpOptions(
    client_args={"proxy": settings.proxy_url},
    base_url=gemini_config.base_url,
    base_url_resource_scope=types.ResourceScope.COLLECTION,
    async_client_args={"proxy": settings.proxy_url},
    retry_options=types.HttpRetryOptions(
        attempts=2,  # 最大请求次数（包含首次，设为 1 则等于禁用重试）
        initial_delay=1.0,  # 首次重试前的延迟（秒）
        max_delay=60.0,  # 最大延迟上限（秒）
        exp_base=2.0,  # 指数退避的底数
        http_status_codes=[408, 429, 500, 502, 503, 504],  # 触发重试的状态码
    ),
    timeout=175 * 1000,
)

# client = (
#     genai.Client(vertexai=True, api_key=vertex_api_key, http_options=http_options)
#     if use_vertexai
#     else genai.Client(api_key=api_key, http_options=http_options)
# )

client = genai.Client(api_key=api_key.get_secret_value(), http_options=http_options)


def handle_gemini_image_response(
    response: GenerateContentResponse, *, include_usage: bool = True
) -> ImageToolResponse:
    if response.parts is None:
        return ImageToolResponse(
            image_model=response.model_version,
            content="LLM未返回任何内容, 可能触发了LLM的过滤与审计机制, 请尝试修改提示词",
            success=False,
            images=[],
            usage=response.usage_metadata.model_dump(exclude_none=True)
            if response.usage_metadata
            else None,
        )
    image_parts = (
        [part for part in response.parts if part.inline_data] if response.parts else []
    )
    images = []
    text = ""
    # candidate = response.candidates[0]
    # for part in candidate.content.parts:
    #     if part.text is not None:
    #         text = part.text
    #         print("方式一: ")
    #         print(text)
    #         continue
    for part in response.parts:
        if part.text is not None:
            text = part.text
    for image_part in image_parts:
        image_bytes = image_part.inline_data.data
        mime_type = image_part.inline_data.mime_type
        extension = mime_type.split("/")[-1].replace("jpeg", "jpg")
        id = str(uuid.uuid7())
        filename = f"{id}.{extension}"
        if image_bytes is None:
            continue
        image_url = upload_image(
            filename, image_bytes, prefix="creative/gemini", rename=False
        )
        if image_url is None:
            continue
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
                file_size=len(image_bytes) if image_bytes else None,
            ).model_dump(exclude_unset=True, exclude_none=True)
        )

    usage = (
        response.usage_metadata.model_dump(exclude_none=True)
        if response.usage_metadata
        else None
    )

    return ImageToolResponse(
        image_model=response.model_version,
        content=text or "",
        success=True,
        images=images,
        usage=usage if include_usage else None,
    )


def image_create_with_gemini(
    prompt: str,
    *,
    image_urls: str | list | None = None,
    aspect_ratio: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
    | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
) -> ImageToolResponse:
    image_model = "gemini-3-pro-image"

    if isinstance(image_urls, str):
        image_urls = [
            i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()
        ]
    elif image_urls is None:
        image_urls = []
    images_bytes: list[bytes] = []
    for item in image_urls:
        # 处理本地文件
        if item.startswith("data:") and "base64;" in item:
            image_bytes = parse_data_url_to_bytes(item)
            images_bytes.append(image_bytes)
        elif item.startswith("http"):
            content = requests.get(item).content
            images_bytes.append(content)
        # 绝对路径
        elif item.startswith("/"):
            pass
        else:
            filename = item
            local_file_path = settings.data_dir / "files" / filename
            content = local_file_path.read_bytes()
            images_bytes.append(content)

    if use_image_url:
        image_parts = []
        for image in image_urls:
            # 判断图像大小
            file_bytes = requests.get(image).content
            mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            print(f"原始图像大小: {len(file_bytes) / (1024 * 1024):.2f} MB")
            if len(file_bytes) > 20 * 1024 * 1024:
                with Image.open(io.BytesIO(file_bytes)) as img:
                    img.thumbnail((1024, 1024))

                    has_alpha = "A" in img.getbands()

                    buf = io.BytesIO()
                    if has_alpha:
                        img.save(buf, format="PNG", optimize=True)
                        mime_type = "image/png"
                    else:
                        img = img.convert("RGB")
                        img.save(buf, format="JPEG", quality=85, optimize=True)
                        mime_type = "image/jpeg"

                    # image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    # data_url = f"data:{mime_type};base64,{image_base64}"
                    image_parts.append(
                        types.Part.from_bytes(data=buf.getvalue(), mime_type=mime_type)
                    )
            elif len(file_bytes) > 10 * 1024 * 1024:
                image_parts.append(
                    types.Part.from_uri(
                        file_uri=f"{image}?x-oss-process=image/resize,l_1024",
                        mime_type=mime_type,
                    )
                )
            else:
                image_parts.append(
                    types.Part.from_uri(file_uri=image, mime_type=mime_type)
                )
            # mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            # image_parts.append(types.Part.from_uri(file_uri=image, mime_type=mime_type))
        contents = [prompt, *image_parts]
    else:
        image_pils = []
        for image in images_bytes:
            image_bytes = BytesIO(image)
            image_pil = Image.open(image_bytes)
            image_pil.thumbnail((1024, 1024))
            image_pils.append(image_pil)
        contents = [prompt, *image_pils]
    try:
        response = client.models.generate_content(
            model=image_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["Text", "Image"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,  # "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", and "21:9"
                    image_size=image_size,  # Literal["1K", "2K", "4K"]
                ),
            ),
        )
        print(f"使用生图模型: {image_model}")
    except errors.ClientError as err:
        if err.code == 400:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 检测参数错误 {err}",
                success=False,
                images=[],
                usage=None,
            )
        elif err.code == 403:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 错误详情:{err}",
                success=False,
                images=[],
                usage=None,
            )
        else:
            raise
    except errors.ServerError as err:
        logging.error(f"服务器错误({err.code}): 错误提示:{err}")
        return ImageToolResponse(
            image_model=image_model,
            content=f"生图失败, 服务器错误, 详情: {err}",
            success=False,
            images=[],
            usage=None,
        )
    return handle_gemini_image_response(response)


def image_create_with_gemini_flash_2(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal[
        "auto",
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "1:8",
        "8:1",
        "21:9",
    ]
    | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
) -> ImageToolResponse:
    return _image_create_with_gemini_flash_2(
        prompt,
        image_model="gemini-3.1-flash-image",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
    )


def image_create_with_gemini_flash_2_1(
    prompt: str,
    *,
    image_urls: str | list[str] | None = None,
    aspect_ratio: Literal[
        "auto",
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "1:8",
        "8:1",
        "21:9",
    ]
    | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
) -> ImageToolResponse:
    return _image_create_with_gemini_flash_2(
        prompt,
        image_model="gemini-nano-banana-2.1",
        image_urls=image_urls,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
    )


def _image_create_with_gemini_flash_2(
    prompt: str,
    *,
    image_model: str,
    image_urls: str | list[str] | None = None,
    aspect_ratio: str | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = None,
) -> ImageToolResponse:
    # 处理image_urls为列表格式
    if isinstance(image_urls, str):
        image_urls = [
            i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()
        ]
    elif image_urls is None:
        image_urls = []

    # 获取图像二进制流
    images_bytes: list[bytes] = []
    for item in image_urls:
        # 处理本地文件
        if item.startswith("data:") and "base64;" in item:
            image_bytes = parse_data_url_to_bytes(item)
            images_bytes.append(image_bytes)
        elif item.startswith("http"):
            content = requests.get(item).content
            images_bytes.append(content)
        # 绝对路径
        elif item.startswith("/"):
            content = Path(item).read_bytes()
            images_bytes.append(content)
        # 处理本地文件类型
        else:
            filename = item
            local_file_path = settings.data_dir / "files" / filename
            content = local_file_path.read_bytes()
            images_bytes.append(content)

    # build contents
    if use_image_url:
        image_parts = []
        for image in image_urls:
            # 判断图像大小
            file_bytes = requests.get(image).content
            mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            print(f"原始图像大小: {len(file_bytes) / (1024 * 1024):.2f} MB")
            if len(file_bytes) > 20 * 1024 * 1024:
                with Image.open(io.BytesIO(file_bytes)) as img:
                    img.thumbnail((1024, 1024))

                    has_alpha = "A" in img.getbands()

                    buf = io.BytesIO()
                    if has_alpha:
                        img.save(buf, format="PNG", optimize=True)
                        mime_type = "image/png"
                    else:
                        img = img.convert("RGB")
                        img.save(buf, format="JPEG", quality=85, optimize=True)
                        mime_type = "image/jpeg"

                    # image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    # data_url = f"data:{mime_type};base64,{image_base64}"
                    image_parts.append(
                        types.Part.from_bytes(data=buf.getvalue(), mime_type=mime_type)
                    )
            elif len(file_bytes) > 10 * 1024 * 1024:
                image_parts.append(
                    types.Part.from_uri(
                        file_uri=f"{image}?x-oss-process=image/resize,l_1024",
                        mime_type=mime_type,
                    )
                )
            else:
                image_parts.append(
                    types.Part.from_uri(file_uri=image, mime_type=mime_type)
                )
            # mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            # image_parts.append(types.Part.from_uri(file_uri=image, mime_type=mime_type))
        contents = [prompt, *image_parts]
    else:
        image_pils = []
        for image in images_bytes:
            image_bytes = BytesIO(image)
            image_pil = Image.open(image_bytes)
            image_pil.thumbnail((1024, 1024))  # 对上传的图片进行压缩
            image_pils.append(image_pil)
        contents = [prompt, *image_pils]
    try:
        print(f"使用{image_model} 进行图像创作")
        response: types.GenerateContentResponse = client.models.generate_content(
            model=image_model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=1,
                top_p=0.95,
                response_modalities=["TEXT", "IMAGE"],
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT", threshold="OFF"
                    ),
                ],
                thinking_config=types.ThinkingConfig(
                    thinking_level=ThinkingLevel.HIGH,
                ),
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,  # "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", and "21:9"
                    image_size=image_size or "2K",  # Literal["1K", "2K", "4K"]
                    # number_of_images=4,
                    # output_mime_type="image/png",
                ),
            ),
        )
    except errors.ClientError as err:
        if err.code == 400:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 请检查参数或图片是否正确 错误详情:{err}",
                success=False,
                images=[],
                usage=None,
            )
        elif err.code == 403:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 错误详情: {err}",
                success=False,
                images=[],
                usage=None,
            )
        else:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 错误详情: {err.message}, status: {err.status}",
                error=f"{err.message}",
                success=False,
                images=[],
                usage=None,
            )
    except errors.ServerError as err:
        return ImageToolResponse(
            image_model=image_model,
            content=f"生图失败({err.code}), 错误详情: {err.message}, status: {err.status}",
            error=f"{err.message}",
            success=False,
            images=[],
            usage=None,
        )
    except Exception as err:
        return ImageToolResponse(
            image_model=image_model,
            content=f"生图失败, 未知错误,  详情: {err}",
            error=f"{err}",
            success=False,
            images=[],
            usage=None,
        )
    return handle_gemini_image_response(response)


def image_create_with_gemini_flash(
    prompt: str,
    *,
    image_urls: str | list | None = None,
    aspect_ratio: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
    | None = None,
    image_size: Literal["1K", "2K", "4K"] | None = "1K",
) -> ImageToolResponse:
    image_model = "gemini-2.5-flash-image"

    if isinstance(image_urls, str):
        image_urls = [
            i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()
        ]
    elif image_urls is None:
        image_urls = []

    if len(image_urls) > 3:
        return ImageToolResponse(
            image_model=image_model,
            content=f"Nano Banana最大支持传入3张图片, 当前传入{len(image_urls)}张",
            success=False,
            images=[],
            usage=None,
        )

    images_bytes: list[bytes] = []
    for item in image_urls:
        # 处理本地文件
        if item.startswith("data:") and "base64;" in item:
            image_bytes = parse_data_url_to_bytes(item)
            images_bytes.append(image_bytes)
        elif item.startswith("http"):
            content = requests.get(item).content
            images_bytes.append(content)
        # 绝对路径
        elif item.startswith("/"):
            pass
        else:
            filename = item
            local_file_path = settings.data_dir / "files" / filename
            content = local_file_path.read_bytes()

            # new = upload_image(filename, content, prefix="files", rename=False)
            images_bytes.append(content)

    if use_image_url:
        image_parts = []
        for image in image_urls:
            # 判断图像大小
            file_bytes = requests.get(image).content
            mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            print(f"原始图像大小: {len(file_bytes) / (1024 * 1024):.2f} MB")
            if len(file_bytes) > 20 * 1024 * 1024:
                with Image.open(io.BytesIO(file_bytes)) as img:
                    img.thumbnail((1024, 1024))

                    has_alpha = "A" in img.getbands()

                    buf = io.BytesIO()
                    if has_alpha:
                        img.save(buf, format="PNG", optimize=True)
                        mime_type = "image/png"
                    else:
                        img = img.convert("RGB")
                        img.save(buf, format="JPEG", quality=85, optimize=True)
                        mime_type = "image/jpeg"

                    # image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    # data_url = f"data:{mime_type};base64,{image_base64}"
                    image_parts.append(
                        types.Part.from_bytes(data=buf.getvalue(), mime_type=mime_type)
                    )
            elif len(file_bytes) > 10 * 1024 * 1024:
                image_parts.append(
                    types.Part.from_uri(
                        file_uri=f"{image}?x-oss-process=image/resize,l_1024",
                        mime_type=mime_type,
                    )
                )
            else:
                image_parts.append(
                    types.Part.from_uri(file_uri=image, mime_type=mime_type)
                )
            # mime_type, _ = mimetypes.guess_type(unquote(urlparse(image).path))
            # image_parts.append(types.Part.from_uri(file_uri=image, mime_type=mime_type))
        contents = [prompt, *image_parts]
    else:
        image_pils = []
        for image in images_bytes:
            image_bytes = BytesIO(image)
            image_pil = Image.open(image_bytes)
            image_pil.thumbnail((1024, 1024))
            image_pils.append(image_pil)
        contents = [prompt, *image_pils]

    if aspect_ratio and aspect_ratio not in [
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "9:16",
        "16:9",
        "21:9",
    ]:
        raise Exception(
            f"aspect_ratio: {aspect_ratio}, 该模型不支持当前分辨率, 仅支持 1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, 21:9."
        )

    try:
        response = client.models.generate_content(
            model=image_model,
            # contents=[prompt, *image_pils],
            contents=contents,
            config=types.GenerateContentConfig(
                # response_modalities=["IMAGE"],
                response_modalities=["Text", "Image"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,  # "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", and "21:9"
                    # number_of_images=4,
                    # output_mime_type=
                ),
            ),
        )
        print(f"使用生图模型: {image_model}")
    except errors.ClientError as err:
        if err.code == 429:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 原因: {err}",
                success=False,
            )
        elif err.code == 403:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败({err.code}), 原因:{err}",
                success=False,
                images=[],
                usage=None,
            )
        elif err.code == 400:
            return ImageToolResponse(
                image_model=image_model,
                content=f"生图失败{err.code}, 请检测参数,原因:{err}",
                success=False,
                images=[],
                usage=None,
            )
        else:
            raise

    return handle_gemini_image_response(response)


def magic_generate_with_gemini(
    prompt: str, image_url: str
) -> tuple[list[dict], dict | None]:
    if image_url.startswith("http"):
        image_bytes = requests.get(image_url).content
        pil_image = Image.open(BytesIO(image_bytes))
    else:
        base_image_path = settings.data_dir.joinpath("files")
        image = base_image_path.joinpath(image_url)
        pil_image = Image.open(image)

    response = client.models.generate_content(
        # model="gemini-3-pro-image-preview",
        model="gemini-2.5-flash-image",
        contents=[prompt, pil_image],
    )
    image_urls = []
    for part in response.candidates[0].content.parts:
        if part.text is not None:
            print(part.text)
        elif part.inline_data is not None:
            image_bytes = part.inline_data.data
            ext = part.inline_data.mime_type.split("/")[-1].replace("jpeg", "jpg")
            filename = f"{str(uuid.uuid4())}.{ext}"
            url = upload_image(
                filename, data=image_bytes, prefix="creative/gemini", rename=False
            )

            image = Image.open(BytesIO(part.inline_data.data))
            width, height = image.size
            image_urls.append(
                dict(
                    image_url=url,
                    mime_type=part.inline_data.mime_type,
                    width=width,
                    height=height,
                )
            )
            # save_path = settings.temp_dir / "generated_image2.png"
            #
            # image.save(save_path)
            # image.show()
            print(f"Image saved to {url}")

    usage = (
        response.usage_metadata.model_dump(exclude_none=True)
        if response.usage_metadata
        else None
    )

    return image_urls, usage


if __name__ == "__main__":
    # magic_generate_with_gemini(image_url="unknown.png")
    # result = image_create_with_gemini("将图片改成写实风格", image_urls="img.png", aspect_ratio="2:3")
    # print(result)
    print(settings.proxy_url)
    result = image_create_with_gemini_flash_2(
        "一碗诱人的红烧牛肉面，大块牛腩，筋道面条，浓郁汤底，点缀葱花和香菜，热气腾腾。专业美食摄影，微距，自然光，8k高清，极具食欲。",
        # image_urls=["https://cdn.fullspeed.cn/creative/gemini/019d099c-3e0d-7be2-8125-81d199eadfd3.png"],
        # image_size="1K",
    )
    print(result)
