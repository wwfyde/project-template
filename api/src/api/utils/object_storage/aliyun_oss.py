import hashlib
import uuid
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.aio import AsyncClient
from PIL import Image

from api.core.config import settings
from api.tools.types import ImageInfo

type MimeType = Literal["image/png", "image/jpeg", "image/webp"]


@lru_cache
def get_oss_client() -> AsyncClient:
    oss_config = settings.oss
    if oss_config is None:
        raise RuntimeError("Aliyun OSS config is required when app.agent_mode is api")



    cfg = oss.config.load_default()
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
        oss_config.access_key_id,
        oss_config.access_key_secret,
    )
    cfg.region = oss_config.region or "cn-hangzhou"
    return AsyncClient(cfg)


async def upload_image(
    filename: str,
    data: bytes,
    *,
    mime_type: MimeType | None = None,
    prefix: str | None = None,
    rename: bool = True,
) -> ImageInfo:
    """Upload image bytes to Aliyun OSS with the v2 async client.

    Returns the uploaded image metadata.
    """
    oss_config = settings.oss
    if oss_config is None:
        raise RuntimeError("Aliyun OSS config is required when app.agent_mode is api")

    import alibabacloud_oss_v2 as oss

    id = str(uuid.uuid7())
    with Image.open(BytesIO(data)) as img:
        width, height = img.size

        mime_type: MimeType = cast(
            MimeType,
            Image.MIME.get(img.format or "image/jpeg") if not mime_type else mime_type,
        )
        extension: Literal["jpg", "png", "webp"] = (
            img.format.lower().replace("jpeg", "jpg") if img.format else "jpg"
        )

        upload_name = f"{id}.{extension}" if rename else Path(filename).name
        storage_prefix = prefix or oss_config.prefix or "tmp"
        storage_key = f"{storage_prefix.strip('/')}/{upload_name}"
        original_address = f"{oss_config.bucket_name}.{oss_config.region or 'cn-hangzhou'}.aliyuncs.com"

        result = await get_oss_client().put_object(
            oss.PutObjectRequest(
                bucket=oss_config.bucket_name,
                key=storage_key,
                body=data,
                content_type=mime_type,
                content_length=len(data),
            )
        )
        if not result.etag:
            raise RuntimeError("Aliyun OSS upload did not return an ETag")

        encoded_key = quote(storage_key)
        sha256 = hashlib.sha256(data).hexdigest()

        domain = oss_config.cdn if oss_config.cdn else original_address
        url = f"https://{domain}/{encoded_key}"
        return ImageInfo(
            url=url,
            id=id,
            filename=upload_name,
            original_filename=filename,
            file_size=len(data),
            mime_type=mime_type,
            extension=extension,
            width=width,
            height=height,
            content="",
            storage_key=storage_key,
            sha256=sha256,
        )


if __name__ == "__main__":
    import asyncio

    file: Path = settings.data_dir.joinpath(
        "creative", "gpt", "019e39bd-faf6-7652-9143-24a02a2beaba.png"
    )
    data = file.read_bytes()
    image = asyncio.run(upload_image(file.name, data, rename=True, prefix="tmp"))
    print(image)
