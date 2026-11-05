"""OSS uploads own and close their real asynchronous HTTP sessions."""

import asyncio
from dataclasses import dataclass, field
from io import BytesIO
from types import SimpleNamespace

import aiohttp
import alibabacloud_oss_v2 as oss
import pytest
from alibabacloud_oss_v2.aio import AsyncClient
from PIL import Image
from pytest import MonkeyPatch

from api.core.config import AliyunOssConfig
from api.utils.object_storage import aliyun_oss


@dataclass
class UploadLifecycle:
    clients: list[AsyncClient] = field(default_factory=list)
    sessions: list[aiohttp.ClientSession] = field(default_factory=list)
    loops: list[asyncio.AbstractEventLoop] = field(default_factory=list)
    failure: str | None = None


@pytest.fixture
def upload_lifecycle(monkeypatch: MonkeyPatch) -> UploadLifecycle:
    lifecycle = UploadLifecycle()
    monkeypatch.setattr(
        aliyun_oss,
        "settings",
        SimpleNamespace(
            oss=AliyunOssConfig(
                bucket_name="test-bucket",
                region="cn-hangzhou",
                access_key_id="test-only-ak",
                access_key_secret="test-only-sk",
            )
        ),
    )

    async def put_object(
        client: AsyncClient, request: oss.PutObjectRequest
    ) -> SimpleNamespace:
        assert request.bucket == "test-bucket"
        lifecycle.clients.append(client)
        lifecycle.loops.append(asyncio.get_running_loop())
        # Exercise the SDK's real session ownership without sending a request.
        transport = client._client._options.http_client
        await transport.open()
        assert isinstance(transport.session, aiohttp.ClientSession)
        lifecycle.sessions.append(transport.session)
        if lifecycle.failure == "request":
            raise RuntimeError("Upload failed")
        return SimpleNamespace(etag=None if lifecycle.failure == "no_etag" else "etag")

    monkeypatch.setattr(AsyncClient, "put_object", put_object)
    return lifecycle


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "request", "no_etag"])
async def test_upload_closes_real_session_on_success_and_failure(
    upload_lifecycle: UploadLifecycle, failure: str | None
) -> None:
    upload_lifecycle.failure = failure
    try:
        if failure:
            with pytest.raises(RuntimeError):
                await aliyun_oss.upload_image("image.png", png())
        else:
            result = await aliyun_oss.upload_image("image.png", png())
            assert result.url
        assert len(upload_lifecycle.sessions) == 1
        assert upload_lifecycle.sessions[0].closed
    finally:
        # Keep regression failures from leaking the session created by the test.
        for client in upload_lifecycle.clients:
            await client.close()


def test_separate_event_loops_receive_fresh_oss_clients(
    upload_lifecycle: UploadLifecycle,
) -> None:
    async def upload() -> None:
        try:
            await aliyun_oss.upload_image("image.png", png())
        finally:
            if upload_lifecycle.clients:
                await upload_lifecycle.clients[-1].close()

    asyncio.run(upload())
    asyncio.run(upload())

    assert len(upload_lifecycle.clients) == 2
    assert upload_lifecycle.clients[0] is not upload_lifecycle.clients[1]
    assert upload_lifecycle.loops[0] is not upload_lifecycle.loops[1]
    assert all(session.closed for session in upload_lifecycle.sessions)
