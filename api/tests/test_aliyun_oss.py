"""Canonical image upload returns real OSS metadata and closes each async client."""

import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pytest import MonkeyPatch

from api.core.config import AliyunOssConfig, settings
from api.utils.object_storage import aliyun_oss


def png() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (4, 3), (10, 20, 30, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeOSSClient:
    def __init__(self) -> None:
        self.put_object = AsyncMock(return_value=SimpleNamespace(etag="etag"))
        self.closed = False
        self.loop = None

    async def __aenter__(self) -> "FakeOSSClient":
        self.loop = asyncio.get_running_loop()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


@pytest.fixture
def oss_env(monkeypatch: MonkeyPatch) -> tuple[object, list[FakeOSSClient]]:
    config = settings.model_copy(deep=True)
    config.oss = AliyunOssConfig(
        bucket_name="test-bucket",
        region="cn-hangzhou",
        access_key_id="test-ak",
        access_key_secret="test-sk",
        prefix="images",
    )
    monkeypatch.setattr(aliyun_oss, "settings", config)
    clients: list[FakeOSSClient] = []

    def factory() -> FakeOSSClient:
        client = FakeOSSClient()
        clients.append(client)
        return client

    monkeypatch.setattr(aliyun_oss, "get_oss_client", factory)
    return config, clients


def test_upload_preserves_metadata_and_uses_a_fresh_closed_client_for_each_loop(
    oss_env: tuple[object, list[FakeOSSClient]],
) -> None:
    _, clients = oss_env
    data = png()
    first = asyncio.run(
        aliyun_oss.upload_image(
            "folder/中文 image.png", data, prefix="creative/gemini", rename=False
        )
    )
    second = asyncio.run(aliyun_oss.upload_image("image.png", data))
    assert len(clients) == 2 and clients[0].loop is not clients[1].loop
    assert all(client.closed for client in clients)
    assert (
        first.url
        == "https://test-bucket.oss-cn-hangzhou.aliyuncs.com/creative/gemini/%E4%B8%AD%E6%96%87%20image.png"
    )
    assert first.filename == "中文 image.png"
    assert first.storage_key == "creative/gemini/中文 image.png"
    assert first.original_filename == "folder/中文 image.png"
    assert first.width == 4 and first.height == 3
    assert first.mime_type == "image/png" and first.image_format == "png"
    assert first.sha256 == hashlib.sha256(data).hexdigest()
    assert first.file_size == len(data)
    assert second.storage_key == f"images/{second.id}.png"
    request = clients[0].put_object.call_args.args[0]
    assert request.bucket == "test-bucket"
    assert request.key == first.storage_key
    assert request.body == data
    assert request.content_type == "image/png"
    assert request.content_length == len(data)


@pytest.mark.parametrize("cdn", ["cdn.example", "https://cdn.example/"])
def test_cdn_is_the_public_image_address(
    oss_env: tuple[object, list[FakeOSSClient]], cdn: str
) -> None:
    config, _ = oss_env
    config.oss.cdn = cdn
    result = asyncio.run(aliyun_oss.upload_image("image.png", png(), rename=False))
    assert result.url == "https://cdn.example/images/image.png"


@pytest.mark.parametrize("failure", ["error", "no_etag"])
def test_failed_upload_also_closes_client(
    monkeypatch: MonkeyPatch, oss_env: tuple[object, list[FakeOSSClient]], failure: str
) -> None:
    client = FakeOSSClient()
    if failure == "error":
        client.put_object.side_effect = RuntimeError("upload failed")
    else:
        client.put_object.return_value = SimpleNamespace(etag=None)
    monkeypatch.setattr(aliyun_oss, "get_oss_client", lambda: client)
    with pytest.raises(RuntimeError):
        asyncio.run(aliyun_oss.upload_image("image.png", png()))
    assert client.closed


def test_bad_image_and_mime_mismatch_are_rejected_before_upload(
    oss_env: tuple[object, list[FakeOSSClient]],
) -> None:
    _, clients = oss_env
    with pytest.raises(ValueError, match="MIME"):
        asyncio.run(aliyun_oss.upload_image("image.png", png(), mime_type="image/jpeg"))
    assert not clients


def test_legacy_names_resolve_to_the_canonical_async_uploader() -> None:
    from api.core import storage, upload_image

    assert upload_image is aliyun_oss.upload_image
    assert storage.upload_image is aliyun_oss.upload_image


def test_http_endpoint_runs_real_seedream_tool_and_canonical_oss_upload(
    monkeypatch: MonkeyPatch, oss_env: tuple[object, list[FakeOSSClient]]
) -> None:
    import httpx2
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.core.config import LLMConfig, get_settings
    from api.routes.ai_tools import ai_tools_router
    from api.tools.images import seedream4_5

    config, clients = oss_env
    config.images.clients = []
    config.providers.volcengine = LLMConfig(
        base_url="https://provider.example/api/v3", api_key="test-provider-key"
    )
    monkeypatch.setattr(seedream4_5, "settings", config)

    def post(url: str, **kwargs: object) -> httpx2.Response:
        assert kwargs["headers"]["Authorization"] == "Bearer test-provider-key"
        assert kwargs["json"]["model"] == "doubao-seedream-4-5-251128"
        assert kwargs["json"]["size"] == "2K"
        return httpx2.Response(
            200,
            request=httpx2.Request("POST", url),
            json={
                "data": [{"url": "https://provider.example/output.png"}],
                "usage": {"generated_images": 1},
            },
        )

    monkeypatch.setattr(seedream4_5.httpx2, "post", post)
    monkeypatch.setattr(
        seedream4_5.httpx2,
        "get",
        lambda url, **kwargs: httpx2.Response(
            200,
            request=httpx2.Request("GET", url),
            content=png(),
        ),
    )
    app = FastAPI()
    app.include_router(ai_tools_router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: config
    with TestClient(app) as client:
        response = client.post(
            "/api/ai-tools/images/seedream/doubao-seedream-4-5-251128",
            json={"prompt": "draw", "image_size": "2K"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True, body
    assert body["image_model"] == "doubao-seedream-4-5-251128"
    assert body["usage"] == {"generated_images": 1}
    image = body["images"][0]
    assert image["url"].startswith(
        "https://test-bucket.oss-cn-hangzhou.aliyuncs.com/creative/seedream/"
    )
    assert image["storage_key"] == f"creative/seedream/{image['filename']}"
    assert image["sha256"] == hashlib.sha256(png()).hexdigest()
    assert image["image_format"] == "png"
    assert len(clients) == 1 and clients[0].closed
