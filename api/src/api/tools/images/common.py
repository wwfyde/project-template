from io import BytesIO
from typing import TypeIs

import httpx2
import uuid_utils
from PIL import Image

from api.tools.types import ImageInfo, MimeType


def get_mime_type(pil_format: str | None) -> MimeType:
    match (pil_format or "png").lower():
        case "png":
            return "image/png"
        case "jpeg" | "jpg":
            return "image/jpeg"
        case "webp":
            return "image/webp"
        case other:
            raise ValueError(f"Unsupported image format: {other}")


def is_mime_type(value: str) -> TypeIs[MimeType]:
    return value in MimeType


def get_image_info(url: str) -> ImageInfo:
    response = httpx2.get(url=url, timeout=180)

    content = response.content
    pil = Image.open(BytesIO(content))
    img_format = pil.format.lower() if pil.format else "png"
    id = str(uuid_utils.uuid7())
    width, height = pil.size
    filename = f"{id}.{img_format.replace('jpeg', 'jpg')}"
    # metadata = {"mime_type": f"image/{img_format}"}

    mime_type = f"image/{img_format}"

    if not is_mime_type(mime_type):
        raise ValueError(f"Unsupported image format: {img_format}")

    return ImageInfo(
        url=url,
        width=width,
        height=height,
        id=id,
        filename=filename,
        mime_type=mime_type,
    )
