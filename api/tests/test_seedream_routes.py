"""Seedream HTTP routes await the shared tool with an explicit model."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from api.images.source_access import ImageSourceError, guard_image_source
from api.routes.ai_tools import ai_tools_router, seedream_40, seedream_55
from api.schemas.ai_tools import Seedream40Request, Seedream55Request
from api.tools.images import seedream
from api.tools.types import ImageToolResponse
from fastapi import FastAPI
from fastapi.testclient import TestClient

PREFIX = "/api/ai-tools/images/seedream"
MODELS = ["doubao-seedream-4-0-250828", "doubao-seedream-5-5-261028"]


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(ai_tools_router, prefix="/api")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("image_size", [None, "1K", "2K"])
def test_seedream_routes_await_shared_tool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, model: str, image_size: str | None
) -> None:
    result = ImageToolResponse(image_model=model, content="done", images=[])
    generate = AsyncMock(return_value=result)
    monkeypatch.setattr(seedream, "image_create_with_seedream", generate)

    response = client.post(
        f"{PREFIX}/{model}",
        json={
            "prompt": "draw",
            "image_urls": ["data:image/png;base64,aGVsbG8="],
            "aspect_ratio": "3:2",
            "image_size": image_size,
        },
    )

    assert response.status_code == 200
    assert response.json() == result.model_dump(mode="json")
    generate.assert_awaited_once_with(
        prompt="draw",
        model=model,
        image=["data:image/png;base64,aGVsbG8="],
        aspect_ratio="3:2",
        image_size=image_size,
    )


@pytest.mark.parametrize("model", MODELS)
def test_seedream_routes_preserve_default_size_and_safe_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    generate = AsyncMock(side_effect=RuntimeError("private-provider-secret"))
    monkeypatch.setattr(seedream, "image_create_with_seedream", generate)

    response = client.post(f"{PREFIX}/{model}", json={"prompt": "draw"})

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["image_model"] == model
    assert response.json()["error"] == "image_tool_failed"
    assert "private-provider-secret" not in response.text
    generate.assert_awaited_once_with(
        prompt="draw", model=model, image=None, aspect_ratio=None, image_size="2K"
    )


def test_seedream_55_accepts_documented_intermediate_size(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    generate = AsyncMock(return_value=ImageToolResponse(content="done"))
    monkeypatch.setattr(seedream, "image_create_with_seedream", generate)

    response = client.post(
        f"{PREFIX}/doubao-seedream-5-5-261028",
        json={"prompt": "draw", "image_size": "1.5K"},
    )

    assert response.status_code == 200
    assert generate.await_args.kwargs["image_size"] == "1.5K"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("failure", [False, True])
async def test_seedream_routes_scope_reference_guard_to_tool_execution(
    monkeypatch: pytest.MonkeyPatch, model: str, failure: bool
) -> None:
    source = "/tmp/private.png"

    async def generate(**kwargs: object) -> ImageToolResponse:
        assert kwargs["image"] == source
        with pytest.raises(ImageSourceError):
            guard_image_source(source)
        if failure:
            raise RuntimeError("mock-provider-failure")
        return ImageToolResponse(image_model=model, content="done")

    tool = AsyncMock(side_effect=generate)
    monkeypatch.setattr(seedream, "image_create_with_seedream", tool)

    guard_image_source(source)
    if model == "doubao-seedream-4-0-250828":
        result = await seedream_40(Seedream40Request(prompt="draw", image_urls=source))
    else:
        result = await seedream_55(Seedream55Request(prompt="draw", image_urls=source))
    guard_image_source(source)

    assert result.success is not failure
    tool.assert_awaited_once()


@pytest.mark.parametrize(
    "body,query",
    [
        ({"image_size": "4K"}, {}),
        ({"background": "transparent"}, {}),
        ({"image_urls": [123]}, {}),
        ({}, {"provider": "openai"}),
    ],
)
def test_seedream_55_rejects_unsupported_http_parameters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
    query: dict[str, str],
) -> None:
    generate = AsyncMock()
    monkeypatch.setattr(seedream, "image_create_with_seedream", generate)

    response = client.post(
        f"{PREFIX}/doubao-seedream-5-5-261028", json={"prompt": "draw", **body}, params=query
    )

    assert response.status_code == 422
    generate.assert_not_awaited()
