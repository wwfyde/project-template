import asyncio

import httpx2

from api.tools.types import ImageInfo
from api.utils.object_storage.aliyun_oss import upload_image


def rembg_with_url(image_url: str) -> ImageInfo:
    from rembg import remove

    response = httpx2.get(image_url, timeout=60)
    response.raise_for_status()
    content = remove(response.content, force_return_bytes=True)
    return asyncio.run(
        upload_image(
            "background-removed.png", content, prefix="tool/remove_backaground"
        )
    )


if __name__ == "__main__":
    url = rembg_with_url(
        "https://dms-upload.oss-cn-hangzhou.aliyuncs.com/seedream/b3736283-44b7-414d-acf0-6920a877942d.jpeg"
    )
    print(url)
