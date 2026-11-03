import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal

import httpx2
from openai import AsyncOpenAI
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputContentParam,
    ResponseInputImageParam,
    ResponseInputParam,
)
from openai.types.responses.response_output_item import ImageGenerationCall
from openai.types.responses.tool_param import (
    ImageGeneration,
    ImageGenerationInputImageMask,
)
from PIL import Image
from pydantic import MISSING, BaseModel, Field

from api.core import settings
from api.tools.images.utils import decode_data_url
from api.tools.types import GPTImageModel, ImageToolResponse
from api.utils.object_storage import upload_image

model_config = settings.providers.openai

type ImageSource = str | bytes | Path | Image.Image


def _image_url(source: ImageSource) -> str:
    """Preserve API-ready URLs; convert local images and raw Base64 as needed."""
    if isinstance(source, str) and source.startswith(("https://", "http://")):
        return source
    encoded = None
    if isinstance(source, str) and source.startswith("data:"):
        if source.startswith("data:image/") and ";base64," in source:
            return source
        data = decode_data_url(source)
    elif isinstance(source, Path):
        data = source.read_bytes()
    elif isinstance(source, Image.Image):
        output = BytesIO()
        source.convert("RGBA").save(output, format="PNG")
        data = output.getvalue()
    elif isinstance(source, str):
        encoded = source
        data = base64.b64decode(encoded, validate=True)
    else:
        data = source
    with Image.open(BytesIO(data)) as image:
        mime_type = Image.MIME.get(image.format or "")
        if mime_type is None:
            raise ValueError("Unsupported image format")
    if encoded is None:
        encoded = base64.b64encode(data).decode()
    return f"data:{mime_type};base64,{encoded}"


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    if model_config is None:
        raise ValueError("CONFIG_MISSING: OpenAI Configuration not provided")
    return AsyncOpenAI(
        api_key=model_config.api_key.get_secret_value(),
        base_url=model_config.base_url,
        http_client=httpx2.AsyncClient(proxy=settings.proxy_url),
    )


class ImageParam(BaseModel):
    size: str | Literal["1024x1024", "1024x1536", "1536x1024", "auto"] = "auto"
    quality: Literal["high", "medium", "low", "auto"] = "low"
    action: Literal["generate", "edit", "auto"] | MISSING = MISSING
    background: Literal["transparent", "opaque", "auto"] = "auto"
    input_fidelity: Literal["high", "low"] | MISSING = MISSING
    model: GPTImageModel = "gpt-image-2.5-flare"
    moderation: Literal["auto", "low"] = "auto"
    output_compression: int | MISSING = Field(
        default=MISSING, ge=0, le=100, description="输出图像的压缩程度"
    )
    output_format: Literal["png", "webp", "jpeg"] = "png"
    partial_images: int | MISSING = Field(
        default=MISSING,
        ge=0,
        le=3,
        description="流式生成过程中的中间预览数量。",
    )


async def image_create_with_gpt_image(
    *,
    prompt: str,
    images: ImageSource
    | ResponseInputImageParam
    | list[ImageSource | ResponseInputImageParam]
    | None
    | MISSING = MISSING,
    image_mask: ImageSource | ImageGenerationInputImageMask | None | MISSING = MISSING,
    image_param: ImageParam = ImageParam(),
) -> ImageToolResponse:
    if model_config is None:
        raise RuntimeError("CONFIG_MISSING: OpenAI Configuration not provided")
    image_model = image_param.model
    main_model = model_config.model

    sources: list[ImageSource | ResponseInputImageParam]
    if images is MISSING or images is None:
        sources = []
    elif isinstance(images, list):
        sources = images
    else:
        sources = [images]
    request_input: str | ResponseInputParam = prompt
    if sources:
        content: list[ResponseInputContentParam] = [
            {"type": "input_text", "text": prompt}
        ]
        for source in sources:
            if isinstance(source, (str, bytes, Path, Image.Image)):
                content.append(
                    ResponseInputImageParam(
                        type="input_image", image_url=_image_url(source), detail="auto"
                    )
                )
            else:
                content.append(source)
        request_input = [EasyInputMessageParam(role="user", content=content)]

    tool = ImageGeneration(
        type="image_generation", **image_param.model_dump(exclude_none=True)
    )
    if image_mask is not MISSING and image_mask is not None:
        if not sources:
            raise ValueError("image_mask requires at least one input image")
        if isinstance(image_mask, str) and image_mask.startswith(
            ("https://", "http://")
        ):
            async with httpx2.AsyncClient(
                proxy=settings.proxy_url, timeout=60, trust_env=False
            ) as image_client:
                mask_response = await image_client.get(image_mask)
                mask_response.raise_for_status()
                image_mask = mask_response.content
        if isinstance(image_mask, (str, bytes, Path, Image.Image)):
            tool["input_image_mask"] = ImageGenerationInputImageMask(
                image_url=_image_url(image_mask)
            )
        else:
            tool["input_image_mask"] = image_mask

    client = get_openai_client()
    response = await client.responses.create(
        model=main_model,
        input=request_input,
        tools=[tool],
        tool_choice={"type": "image_generation"},
    )
    usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    uploaded_images: list[dict] = []
    for output in response.output:
        if not isinstance(output, ImageGenerationCall) or not output.result:
            continue
        metadata = await upload_image(
            "generated.png",
            base64.b64decode(output.result, validate=True),
            prefix="creative/gpt",
        )
        uploaded_images.append(metadata.model_dump(mode="json", exclude_none=True))

    return ImageToolResponse(
        image_model=image_model,
        content=response.output_text
        or ("" if uploaded_images else "模型未返回图片，请调整提示词后重试"),
        success=bool(uploaded_images),
        error=None if uploaded_images else "no_image_returned",
        images=uploaded_images,
        usage=usage,
    )


if __name__ == "__main__":
    import asyncio

    image = asyncio.run(
        image_create_with_gpt_image(
            prompt="将图像改成卡通风格,里面添加一只猫",
            images="https://cdn.fullspeed.cn/creative/gpt/01a1a097-a701-7264-8b15-bd94dffcfe7a.png",
        )
    )

    print(image)
