"""Private skill archives in application-owned Aliyun OSS."""

from typing import cast

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.aio import AsyncClient
from alibabacloud_oss_v2.types import AsyncStreamBody

from api.core.config import AliyunOssConfig
from api.skills.contracts import SkillFailure

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


class AliyunSkillObjectStorage:
    """Each operation owns its client and never generates a public object URL."""

    def __init__(self, config: AliyunOssConfig) -> None:
        self.config = config

    def _client(self) -> AsyncClient:
        config = oss.config.load_default()
        config.credentials_provider = oss.credentials.StaticCredentialsProvider(
            self.config.access_key_id, self.config.access_key_secret
        )
        config.region = self.config.region or "cn-hangzhou"
        if self.config.endpoint:
            config.endpoint = self.config.endpoint
        return AsyncClient(config)

    async def put(self, key: str, content: bytes) -> None:
        if len(content) > MAX_ARCHIVE_BYTES:
            raise SkillFailure("archive_too_large", "Skill archive exceeds 50 MiB.", 413)
        try:
            async with self._client() as client:
                result = await client.put_object(
                    oss.PutObjectRequest(
                        bucket=self.config.bucket_name,
                        key=key,
                        body=content,
                        content_length=len(content),
                        content_type="application/zip",
                        cache_control="private, no-store",
                        acl="private",
                        forbid_overwrite=True,
                    )
                )
                if not result.etag:
                    raise RuntimeError("Missing upload acknowledgement")
        except Exception as exc:
            raise SkillFailure(
                "object_storage_unavailable", "Skill object storage is unavailable.", 503
            ) from exc

    async def get(self, key: str) -> bytes:
        try:
            async with self._client() as client:
                result = await client.get_object(
                    oss.GetObjectRequest(
                        bucket=self.config.bucket_name,
                        key=key,
                    )
                )
                if result.body is None:
                    raise RuntimeError("Missing object stream")
                async with cast(AsyncStreamBody, result.body) as body:
                    if (
                        result.content_length is not None
                        and result.content_length > MAX_ARCHIVE_BYTES
                    ):
                        raise SkillFailure(
                            "archive_too_large", "Stored skill archive is too large.", 502
                        )
                    content = bytearray()
                    async for chunk in body.iter_bytes():
                        if len(content) + len(chunk) > MAX_ARCHIVE_BYTES:
                            raise SkillFailure(
                                "archive_too_large", "Stored skill archive is too large.", 502
                            )
                        content.extend(chunk)
                    return bytes(content)
        except SkillFailure:
            raise
        except Exception as exc:
            raise SkillFailure(
                "object_storage_unavailable", "Skill object storage is unavailable.", 503
            ) from exc

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as client:
                await client.delete_object(
                    oss.DeleteObjectRequest(
                        bucket=self.config.bucket_name,
                        key=key,
                    )
                )
        except Exception as exc:
            raise SkillFailure(
                "object_storage_unavailable", "Skill object storage is unavailable.", 503
            ) from exc
