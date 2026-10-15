import hashlib
import tempfile
from io import BytesIO
from pathlib import Path

import httpx2
import uuid_utils as uuid
from PIL import Image
from api.core import upload_image
from api.tools.types import ImageInfo
from rembg import remove


def rembg_with_url(image_url: str) -> ImageInfo:
    image_content = httpx2.get(image_url, timeout=60).content
    suffix = Path(httpx2.URL(image_url).path).suffix
    with tempfile.NamedTemporaryFile(mode="w+b", suffix=suffix, delete=False) as tmp:
        tmp.write(image_content)
        tmp.flush()
        image_path = tmp.name

    with open(image_path, "rb") as i:
        input = i.read()
        content = remove(input, force_return_bytes=True)

        pil = Image.open(BytesIO(content))
        img_format = pil.format.lower() or "png"
        id = str(uuid.uuid7())
        filename = f"{id}.{img_format.replace('jpeg', 'jpg')}"
        image_url = upload_image(filename, data=content, prefix="tool/remove_backaground", rename=False)
        # metadata = {"mime_type": f"image/{img_format}"}
        width, height = pil.size
        sha256 = hashlib.sha256(content).hexdigest()

        return ImageInfo(
            url=image_url,
            width=width,
            height=height,
            id=id,
            filename=filename,
            mime_type=f"image/{img_format}",  # noqa
            content=f"{image_url})",
            sha256=sha256,
        )


if __name__ == "__main__":
    url = rembg_with_url(
        "https://dms-upload.oss-cn-hangzhou.aliyuncs.com/seedream/b3736283-44b7-414d-acf0-6920a877942d.jpeg"
    )
    print(url)
