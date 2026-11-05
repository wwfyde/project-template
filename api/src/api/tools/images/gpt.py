import base64
from collections.abc import Iterable
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal, cast

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
from api.tools.types import GPTImageGenerationParams, GPTImageModel, ImageToolResponse
from api.utils.object_storage import upload_image

model_config = settings.providers.openai

type ImageSource = str | bytes | Path | Image.Image
type ImageInput = ImageSource | ResponseInputImageParam


async def _image_url(
    source: ImageSource, *, convert_image_url_to_base64: bool = True
) -> str:
    """Download HTTP images when requested; preserve existing Base64 data URLs."""
    if isinstance(source, str) and source.startswith(("https://", "http://")):
        if not convert_image_url_to_base64:
            return source
        async with httpx2.AsyncClient(
            proxy=settings.proxy_url,
            timeout=60,
            trust_env=False,
            follow_redirects=True,
        ) as image_client:
            image_response = await image_client.get(source)
            image_response.raise_for_status()
            source = image_response.content
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
    images: ImageInput | Iterable[ImageInput] | None | MISSING = MISSING,
    mask: ImageSource | ImageGenerationInputImageMask | None | MISSING = MISSING,
    model: GPTImageModel = "gpt-image-2.5-flare",
    image_param: ImageParam = ImageParam(),
) -> ImageToolResponse:
    if model_config is None:
        raise RuntimeError("CONFIG_MISSING: OpenAI Configuration not provided")
    image_model = model
    main_model = model_config.model

    sources: list[ImageInput]
    if images is MISSING or images is None:
        sources = []
    elif isinstance(images, (str, bytes, Path, Image.Image)):
        sources = [images]
    elif isinstance(images, dict):
        # A native image part is one input, not an iterable of its keys.
        sources = [cast(ResponseInputImageParam, images)]
    else:
        sources = list(images)
    request_input: str | ResponseInputParam = prompt
    if sources:
        content: list[ResponseInputContentParam] = [
            {"type": "input_text", "text": prompt}
        ]
        for source in sources:
            image_input: ResponseInputImageParam
            if isinstance(source, (str, bytes, Path, Image.Image)):
                image_input = ResponseInputImageParam(
                    type="input_image",
                    image_url=await _image_url(source),
                    detail="auto",
                )
            else:
                image_input = source.copy()
                image_url = image_input.get("image_url")
                if image_url:
                    image_input["image_url"] = await _image_url(image_url)
            content.append(image_input)
        request_input = [EasyInputMessageParam(role="user", content=content)]

    tool = ImageGeneration(
        type="image_generation", **image_param.model_dump(exclude_none=True)
    )
    if mask is not MISSING and mask is not None:
        if not sources:
            raise ValueError("image_mask requires at least one input image")
        mask_input: ImageGenerationInputImageMask
        if isinstance(mask, (str, bytes, Path, Image.Image)):
            mask_input = ImageGenerationInputImageMask(
                image_url=await _image_url(mask, convert_image_url_to_base64=True)
            )
        else:
            mask_input = mask.copy()
            mask_url = mask_input.get("image_url")
            if mask_url:
                mask_input["image_url"] = await _image_url(
                    mask_url, convert_image_url_to_base64=True
                )
        tool["input_image_mask"] = mask_input

    client = get_openai_client()
    response = await client.responses.create(
        model=main_model,
        input=request_input,
        tools=[tool],
        tool_choice={"type": "image_generation"},
    )
    usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    tool_params = {
        "prompt": prompt,
        **{key: value for key, value in tool.items() if key != "type"},
    }
    for response_tool in response.tools or []:
        if response_tool.type == "image_generation":
            tool_params.update(
                response_tool.model_dump(
                    exclude={"type"}, exclude_none=True, exclude_unset=True
                )
            )
            break
    if "revised_prompt" in tool_params:
        tool_params["prompt"] = tool_params.pop("revised_prompt")
    call_params: list[GPTImageGenerationParams] = []
    uploaded_images: list[dict] = []
    for output in response.output:
        if not isinstance(output, ImageGenerationCall):
            continue
        output_params = output.model_dump(
            exclude={"result"}, exclude_none=True, exclude_unset=True
        )
        if "revised_prompt" in output_params:
            output_params["prompt"] = output_params.pop("revised_prompt")
        call_params.append(
            GPTImageGenerationParams.model_validate({**tool_params, **output_params})
        )
        if not output.result:
            continue
        metadata = await upload_image(
            "generated.png",
            base64.b64decode(output.result, validate=True),
            prefix="creative/gpt",
        )
        uploaded_images.append(metadata.model_dump(mode="json", exclude_none=True))

    generation_params = GPTImageGenerationParams.model_validate(tool_params)
    if len(call_params) == 1:
        generation_params = call_params[0]
    elif call_params:
        generation_params = GPTImageGenerationParams(calls=call_params)

    return ImageToolResponse(
        image_model=image_model,
        content=response.output_text
        or ("" if uploaded_images else "模型未返回图片，请调整提示词后重试"),
        success=bool(uploaded_images),
        error=None if uploaded_images else "no_image_returned",
        images=uploaded_images,
        usage=usage,
        generation_params=generation_params,
        instructions=prompt,
    )


async def image_create_with_image_api(
    *,
    prompt: str,
    images: ImageInput | Iterable[ImageInput] | None | MISSING = MISSING,
    mask: ImageSource | ImageGenerationInputImageMask | None | MISSING = MISSING,
    model: GPTImageModel = "gpt-image-2.5-flare",
    image_param: ImageParam = ImageParam(),
) -> ImageToolResponse:
    """Use the Images API; auto selects editing when reference images are present."""
    if model_config is None:
        raise RuntimeError("CONFIG_MISSING: OpenAI Configuration not provided")

    sources: list[ImageInput]
    if images is MISSING or images is None:
        sources = []
    elif isinstance(images, (str, bytes, Path, Image.Image)):
        sources = [images]
    elif isinstance(images, dict):
        sources = [cast(ResponseInputImageParam, images)]
    else:
        sources = list(images)

    action = image_param.action
    if action is MISSING or action == "auto":
        action = "edit" if sources else "generate"
    if action == "edit" and not sources:
        raise ValueError("action='edit' requires at least one input image")
    if action == "generate" and (sources or (mask is not MISSING and mask is not None)):
        raise ValueError("action='generate' does not accept images or mask")

    client = get_openai_client()

    async def image_file(
        source: ImageInput | ImageGenerationInputImageMask, name: str
    ) -> tuple[str, bytes, str]:
        if not isinstance(source, (str, bytes, Path, Image.Image)):
            image_url = source.get("image_url")
            file_id = source.get("file_id")
            if bool(image_url) == bool(file_id):
                raise ValueError(
                    "Image input requires exactly one of image_url or file_id"
                )
            if image_url:
                source = image_url
            else:
                assert file_id is not None
                source = (await client.files.content(file_id)).content

        if isinstance(source, bytes):
            data = source
        elif isinstance(source, Path):
            data = source.read_bytes()
        elif isinstance(source, Image.Image):
            output = BytesIO()
            source.convert("RGBA").save(output, format="PNG")
            data = output.getvalue()
        elif source.startswith("data:"):
            data = decode_data_url(source)
        elif source.startswith(("https://", "http://")):
            async with httpx2.AsyncClient(
                proxy=settings.proxy_url,
                timeout=60,
                trust_env=False,
                follow_redirects=True,
            ) as image_client:
                image_response = await image_client.get(source)
                image_response.raise_for_status()
                data = image_response.content
        else:
            data = base64.b64decode(source, validate=True)
        with Image.open(BytesIO(data)) as image:
            image_format = image.format or ""
            mime_type = Image.MIME.get(image_format)
            if mime_type is None:
                raise ValueError("Unsupported image format")
        return f"{name}.{image_format.lower()}", data, mime_type

    params = image_param.model_dump(
        exclude_none=True, exclude={"action", "model", "partial_images"}
    )
    if action == "generate":
        params.pop("input_fidelity", None)
        response = await client.images.generate(
            prompt=prompt, model=model, stream=False, **params
        )
    else:
        image_files = [
            await image_file(source, f"reference-{index}")
            for index, source in enumerate(sources)
        ]
        if mask is not MISSING and mask is not None:
            params["mask"] = await image_file(mask, "mask")
        # The API supports moderation; the SDK edit signature has no keyword yet.
        moderation = params.pop("moderation")
        response = await client.images.edit(
            image=image_files,
            prompt=prompt,
            model=model,
            stream=False,
            extra_body={"moderation": moderation},
            **params,
        )

    usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    output_format = response.output_format or image_param.output_format
    generation_values = {
        "prompt": prompt,
        "model": model,
        "action": action,
        "moderation": image_param.moderation,
        **{key: value for key, value in params.items() if key != "mask"},
        **response.model_dump(
            exclude={"data", "usage", "created"},
            exclude_none=True,
            exclude_unset=True,
        ),
    }
    if "revised_prompt" in generation_values:
        generation_values["prompt"] = generation_values.pop("revised_prompt")
    image_params: list[GPTImageGenerationParams] = []
    uploaded_images: list[dict] = []
    for image in response.data or []:
        output_params = image.model_dump(
            exclude={"b64_json", "url"}, exclude_none=True, exclude_unset=True
        )
        if "revised_prompt" in output_params:
            output_params["prompt"] = output_params.pop("revised_prompt")
        image_params.append(
            GPTImageGenerationParams.model_validate(
                {**generation_values, **output_params}
            )
        )
        if not image.b64_json:
            continue
        metadata = await upload_image(
            f"generated.{output_format}",
            base64.b64decode(image.b64_json, validate=True),
            prefix="creative/gpt",
        )
        uploaded_images.append(metadata.model_dump(mode="json", exclude_none=True))

    generation_params = GPTImageGenerationParams.model_validate(generation_values)
    if len(image_params) == 1:
        generation_params = image_params[0]
    elif image_params:
        generation_params = GPTImageGenerationParams(calls=image_params)

    return ImageToolResponse(
        image_model=model,
        content="" if uploaded_images else "模型未返回图片，请调整提示词后重试",
        success=bool(uploaded_images),
        error=None if uploaded_images else "no_image_returned",
        images=uploaded_images,
        usage=usage,
        generation_params=generation_params,
        instructions=prompt,
    )


if __name__ == "__main__":
    import asyncio

    # image = asyncio.run(
    #     image_create_with_gpt_image(
    #         prompt="将图像改成卡通风格,里面添加一只猫",
    #         images="https://cdn.fullspeed.cn/creative/gpt/01a1a097-a701-7264-8b15-bd94dffcfe7a.png",
    #     )
    # )
    image = asyncio.run(
        image_create_with_image_api(
            prompt="将图像改成卡通风格,里面添加一只猫",
            images="https://cdn.fullspeed.cn/creative/gpt/01a1a097-a701-7264-8b15-bd94dffcfe7a.png",
        )
    )

    print(image)
