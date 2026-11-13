"""Private OSS objects, bounded downloads, and client/stream lifecycle."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace

import aiohttp
import alibabacloud_oss_v2 as oss
import pytest
from alibabacloud_oss_v2.aio import AsyncClient
from api.core.config import AliyunOssConfig
from api.skills import objects
from api.skills.contracts import SkillFailure
from api.skills.objects import AliyunSkillObjectStorage
from pytest import MonkeyPatch


@dataclass
class FakeBody:
    chunks: list[bytes] = field(default_factory=lambda: [b"zip", b" bytes"])
    closed: bool = False
    failure: bool = False

    async def __aenter__(self) -> "FakeBody":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if self.failure:
                raise RuntimeError("private transport details")
            yield chunk


@dataclass
class Lifecycle:
    clients: list[AsyncClient] = field(default_factory=list)
    sessions: list[aiohttp.ClientSession] = field(default_factory=list)
    requests: list[object] = field(default_factory=list)
    body: FakeBody = field(default_factory=FakeBody)
    failure: str | None = None
    content_length: int | None = 9


@pytest.fixture
def lifecycle(monkeypatch: MonkeyPatch) -> Lifecycle:
    lifecycle = Lifecycle()

    async def record(client: AsyncClient, request: object) -> None:
        lifecycle.clients.append(client)
        lifecycle.requests.append(request)
        transport = client._client._options.http_client
        await transport.open()
        lifecycle.sessions.append(transport.session)
        if lifecycle.failure == "request":
            raise RuntimeError("private credentials must never be returned")

    async def put(client: AsyncClient, request: oss.PutObjectRequest) -> SimpleNamespace:
        await record(client, request)
        return SimpleNamespace(etag=None if lifecycle.failure == "etag" else "etag")

    async def get(client: AsyncClient, request: oss.GetObjectRequest) -> SimpleNamespace:
        await record(client, request)
        return SimpleNamespace(body=lifecycle.body, content_length=lifecycle.content_length)

    async def delete(client: AsyncClient, request: oss.DeleteObjectRequest) -> None:
        await record(client, request)

    monkeypatch.setattr(AsyncClient, "put_object", put)
    monkeypatch.setattr(AsyncClient, "get_object", get)
    monkeypatch.setattr(AsyncClient, "delete_object", delete)
    return lifecycle


@pytest.fixture
def storage() -> AliyunSkillObjectStorage:
    return AliyunSkillObjectStorage(
        AliyunOssConfig(
            bucket_name="test-skill-bucket",
            region="cn-hangzhou",
            access_key_id="test-ak",
            access_key_secret="test-sk",
        )
    )


def test_custom_oss_service_endpoint_is_used(monkeypatch: MonkeyPatch) -> None:
    received: list[oss.config.Config] = []

    def client(config: oss.config.Config) -> None:
        received.append(config)

    monkeypatch.setattr(objects, "AsyncClient", client)
    config = AliyunOssConfig(
        bucket_name="test-skill-bucket",
        region="cn-hangzhou",
        access_key_id="test-ak",
        access_key_secret="test-sk",
        endpoint="https://oss-cn-hangzhou-internal.aliyuncs.com",
    )
    AliyunSkillObjectStorage(config)._client()
    assert received[0].endpoint == config.endpoint
    assert received[0].region == "cn-hangzhou"


@pytest.mark.asyncio
async def test_upload_sets_private_acl_and_prevents_overwrite(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
) -> None:
    await storage.put("skills/id/version.zip", b"zip bytes")
    request = lifecycle.requests[0]
    assert request.bucket == "test-skill-bucket"
    assert request.key == "skills/id/version.zip"
    assert request.acl == "private"
    assert request.forbid_overwrite is True
    assert request.body == b"zip bytes" and request.content_length == 9
    assert request.content_type == "application/zip"
    assert request.cache_control == "private, no-store"
    assert all(session.closed for session in lifecycle.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["request", "etag"])
async def test_upload_errors_close_client_and_hide_transport_details(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
    failure: str,
) -> None:
    lifecycle.failure = failure
    with pytest.raises(SkillFailure) as error:
        await storage.put("skills/id/version.zip", b"zip")
    assert error.value.status == 503
    assert "private" not in error.value.message
    assert all(session.closed for session in lifecycle.sessions)


@pytest.mark.asyncio
async def test_download_and_delete_use_fresh_clients_and_close_streams(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
) -> None:
    assert await storage.get("skills/id/version.zip") == b"zip bytes"
    assert lifecycle.body.closed
    await storage.delete("skills/id/version.zip")
    assert lifecycle.clients[0] is not lifecycle.clients[1]
    assert all(session.closed for session in lifecycle.sessions)
    assert all(request.key == "skills/id/version.zip" for request in lifecycle.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_length", [9, None, 2])
async def test_download_limit_does_not_trust_content_length(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
    monkeypatch: MonkeyPatch,
    content_length: int | None,
) -> None:
    monkeypatch.setattr(objects, "MAX_ARCHIVE_BYTES", 5)
    lifecycle.content_length = content_length
    with pytest.raises(SkillFailure) as error:
        await storage.get("skills/id/version.zip")
    assert (error.value.code, error.value.status) == ("archive_too_large", 502)
    assert lifecycle.body.closed
    assert all(session.closed for session in lifecycle.sessions)


@pytest.mark.asyncio
async def test_stream_failure_closes_body_and_transport(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
) -> None:
    lifecycle.body.failure = True
    with pytest.raises(SkillFailure) as error:
        await storage.get("skills/id/version.zip")
    assert error.value.status == 503 and "private" not in error.value.message
    assert lifecycle.body.closed
    assert all(session.closed for session in lifecycle.sessions)


@pytest.mark.asyncio
async def test_delete_failure_can_be_retried_and_closes_client(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
) -> None:
    lifecycle.failure = "request"
    with pytest.raises(SkillFailure):
        await storage.delete("skills/id/version.zip")
    assert all(session.closed for session in lifecycle.sessions)


@pytest.mark.asyncio
async def test_oversized_upload_fails_before_creating_client(
    storage: AliyunSkillObjectStorage,
    lifecycle: Lifecycle,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(objects, "MAX_ARCHIVE_BYTES", 5)
    with pytest.raises(SkillFailure) as error:
        await storage.put("skills/id/version.zip", b"123456")
    assert error.value.status == 413
    assert lifecycle.clients == []
