import base64
import io
import uuid
from typing import Literal

import httpx2
from PIL import Image
from openai import OpenAI

from api.core import upload_image
from api.lib.config import settings
from api.tools.types import ImageInfo, ImageToolResponse

llm_config = settings.providers.openai
if llm_config is None:
    raise ValueError("Provider ")
client = OpenAI(
    api_key=llm_config.api_key,
    http_client=httpx2.Client(proxy=settings.proxy_url or "http://127.0.0.1:7890"),
)


def image_create_with_gpt_image_2(
        prompt: str,
        *,
        image_urls: str | list | None = None,
        aspect_ratio: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"] | None = None,
        image_size: Literal["1K", "2K", "4K"] | None = None,
        provider: Literal['openai', 'openrouter', 'evolink'] = "openai",
        quality: Literal["low", "medium", "high", "auto"] = "low",
):
    image_model = "gpt-image-2"
    if provider == "openai":
        llm_config = settings.providers.openai
    else:
        llm_config = settings.providers.openrouter
    if llm_config is None:
        raise ValueError("Provider config is required")

    # TODO resolve image_urls to list[str]
    if isinstance(image_urls, str):
        image_urls = [i.strip() for i in image_urls.replace("，", ",").split(",") if i.strip()]
    elif image_urls is None:
        image_urls = []

    if len(image_urls) < 1:
        response = client.images.generate(
            prompt=prompt,
            model=image_model,
            quality=quality,
            size=aspect_ratio if aspect_ratio else "auto",
        )
    else:
        response = client.images.edit(
            prompt=prompt,
            model=image_model,
            image=image_urls,
            size=aspect_ratio if aspect_ratio else "auto",
            quality=quality,

        )
    if response.data is None or len(response.data) == 0:
        return ImageToolResponse(
            image_model=image_model,
            content="LLM未返回任何内容, 可能触发了LLM的过滤与审计机制, 请尝试修改提示词",
            success=False,
            images=[],
            usage=response.usage.model_dump(exclude_none=True) if response.usage else None
        )
    images = []
    text = ""
    for image in response.data:
        image_base64 = image.b64_json
        if image_base64 is None:
            continue
        mime_type = f"image/{response.output_format}" if response.output_format else None
        extension = response.output_format.replace("jpeg", "jpg") if response.output_format else "jpg"
        id = str(uuid.uuid7())
        filename = f"{id}.{extension}"
        image_bytes = base64.b64decode(image_base64)
        image_url = upload_image(filename, image_bytes, prefix="creative/gpt", rename=False)
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
    usage = response.usage.model_dump(exclude_none=True) if response.usage else None
    return ImageToolResponse(
        image_model=image_model,
        content=text or "",
        success=True,
        images=images,
        usage=usage,
    )


if __name__ == "__main__":
    image = image_create_with_gpt_image_2(
        "35mm film photography with harsh convenience store fluorescent lighting mixed with colorful neon signs from outside, authentic film grain, high contrast, slight color cast, cinematic street editorial style, intimate medium shot, early 20s sexy Chinese female idol with ultra-realistic delicate refined Chinese features, seductive almond-shaped fox eyes with natural double eyelids, high nose bridge, small sharp V-shaped jawline, flawless porcelain skin with cool ivory undertone and visible specular highlights from fluorescent light, subtle skin texture and micro pores, natural dewy makeup with soft flush on cheeks, glossy natural pink lips slightly parted, subtle natural freckles across nose and cheeks, long dark brown hair in a messy high ponytail with many loose strands falling around face and neck, wearing an oversized white button-up shirt as the only top, unbuttoned at the top with deep cleavage and loosely tied at the waist, paired with a tiny black pleated mini skirt, barefoot in simple white slides, seductive casual leaning pose against the glass door of a 24-hour convenience store at late night, body slightly arched, one leg bent with foot resting against the door frame, the other leg straight, one hand holding a bottle of iced drink, the other hand lightly pulling the hem of her mini skirt, intensely seductive playful yet slightly vulnerable gaze straight at the viewer with soft doe eyes full of quiet temptation and teasing smile, bright cold fluorescent store light from inside mixed with pink and blue neon glow from outside signs, realistic reflections on glass door, blurred convenience store interior with shelves and snacks in background, authentic 35mm film color grading with harsh lighting and neon accents, extremely sharp yet soft skin rendering, natural hair strands, realistic fabric wrinkles and drape on the oversized shirt and mini skirt, no plastic skin, no digital over-sharpening, no airbrushing, no blemishes, no moles, no oily skin, no watermark, no text, authentic late-night convenience store atmosphere",
        quality="low"
    )
