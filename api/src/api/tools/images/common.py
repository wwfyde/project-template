from io import BytesIO

import httpx2
import uuid_utils
from PIL import Image

from api.tools.types import ImageInfo

allowed_mime_types = [
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
]


def get_image_info(url: str) -> ImageInfo:
    response = httpx2.get(url=url, timeout=180)

    content = response.content
    pil = Image.open(BytesIO(content))
    img_format = pil.format.lower() if pil.format else "png"
    id = str(uuid_utils.uuid7())
    width, height = pil.size
    filename = f"{id}.{img_format.replace('jpeg', 'jpg')}"
    # metadata = {"mime_type": f"image/{img_format}"}

    return ImageInfo(
        url=url,
        width=width,
        height=height,
        id=id,
        filename=filename,
        mime_type=f"image/{img_format}",  # noqa
    )
