"""Fixed image endpoints reuse real tool signatures and unified responses."""

import asyncio
import inspect
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis_fastapi import SessionStore, get_session_store

from api.routes.ai_tools import ai_tools_router
from api.tools.types import ImageToolResponse
from test_auth_routes import COOKIE_NAME, AuthTestEnvironment, auth_env as auth_env

PREFIX = "/api/ai-tools/images"
MODELS = [
    (
        "gemini/gemini-2.5-flash-image",
        "gemini",
        "image_create_with_gemini_flash",
        "google",
    ),
    ("gemini/gemini-3-pro-image", "gemini", "image_create_with_gemini", "google"),
    (
        "gemini/gemini-3.1-flash-image",
        "gemini",
        "image_create_with_gemini_flash_2",
        "google",
    ),
    (
        "gemini/gemini-nano-banana-2.1",
        "gemini",
        "image_create_with_gemini_flash_2_1",
        "google",
    ),
    (
        "seedream/doubao-seedream-4-0-250828",
        "seedream",
        "image_create_with_seedream",
        "volcengine",
    ),
    (
        "seedream/doubao-seedream-4-5-251128",
        "seedream4_5",
        "image_create_with_seedream4_5",
        "volcengine",
    ),
    (
        "seedream/doubao-seedream-5-0-260128",
        "seedream5_lite",
        "image_create_with_seedream5_lite",
        "volcengine",
    ),
    (
        "seedream/doubao-seedream-5-0-pro-260628",
        "seedream5_pro",
        "image_create_with_seedream5_pro",
        "volcengine",
    ),
    ("gpt/gpt-image-2", "gpt", "image_create_with_gpt_image_2", "openai"),
    (
        "gpt/gpt-image-2.5-flare",
        "gpt",
        "image_create_with_gpt_image_2_5_flare",
        "openai",
    ),
    (
        "gpt/gpt-image-2.5-sunburst",
        "gpt",
        "image_create_with_gpt_image_2_5_sunburst",
        "openai",
    ),
]
GPT_PATH = f"{PREFIX}/gpt/gpt-image-2"
SEEDREAM_PATH = f"{PREFIX}/seedream/doubao-seedream-4-5-251128"
GEMINI_PATH = f"{PREFIX}/gemini/gemini-3.1-flash-image"


@dataclass
class ToolCalls:
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    defaults: dict[str, dict[str, object]] = field(default_factory=dict)
    result: ImageToolResponse = field(
        default_factory=lambda: ImageToolResponse(
            image_model="test-image",
            content="done",
            success=True,
            images=[
                {
                    "url": "https://cdn.example/image.png",
                    "id": "oss-id",
                    "storage_key": "creative/image.png",
                    "sha256": "digest",
                }
            ],
            usage={"total_tokens": 12},
            input_params={"size": "2K"},
            data={"trace": "tool"},
        )
    )
    error: Exception | None = None
    thread_ids: list[int] = field(default_factory=list)

    def run(
        self, function_name: str, parameters: dict[str, object]
    ) -> ImageToolResponse:
        # Sync tool code must be able to use asyncio.run for its async OSS upload.
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        self.thread_ids.append(threading.get_ident())
        self.calls.append((function_name, parameters))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def tool_calls(monkeypatch: MonkeyPatch) -> ToolCalls:
    calls = ToolCalls()
    for _, module_name, function_name, _ in MODELS:
        module = import_module(f"api.tools.images.{module_name}")
        calls.defaults[function_name] = {
            name: parameter.default
            for name, parameter in inspect.signature(
                getattr(module, function_name)
            ).parameters.items()
            if parameter.default is not inspect.Parameter.empty
        }

        def fake(*, _name: str = function_name, **kwargs: object) -> ImageToolResponse:
            return calls.run(_name, kwargs)

        monkeypatch.setattr(module, function_name, fake)
    return calls


@pytest.fixture
def client(tool_calls: ToolCalls) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(ai_tools_router, prefix="/api")
    with TestClient(app) as client:
        yield client


def test_fixed_endpoints_use_tool_signatures_and_image_tool_response_schema() -> None:
    from api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    schema = app.openapi()
    paths = {path for path in schema["paths"] if path.startswith(PREFIX)}
    assert paths == {f"{PREFIX}/{path}" for path, _, _, _ in MODELS}
    assert all("{" not in path for path in paths)
    for path, module, function_name, provider in MODELS:
        operation = schema["paths"][f"{PREFIX}/{path}"]["post"]
        assert "security" not in operation
        assert (
            operation["responses"]["200"]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/ImageToolResponse"
        )
        reference = operation["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ].rsplit("/", 1)[1]
        body = schema["components"]["schemas"][reference]
        tool = getattr(import_module(f"api.tools.images.{module}"), function_name)
        parameters = inspect.signature(tool).parameters
        assert set(body["properties"]) == set(parameters) - {"provider"}
        assert set(body["required"]) == {
            name
            for name, param in parameters.items()
            if param.default is inspect.Parameter.empty
        }
        for name, param in parameters.items():
            if name != "provider" and param.default is not inspect.Parameter.empty:
                assert body["properties"][name].get("default") == param.default
        query = {item["name"]: item for item in operation["parameters"]}
        assert query["provider"]["schema"]["default"] == provider
        assert "stream" not in query
        assert body["additionalProperties"] is False


@pytest.mark.parametrize("path,module,function_name,provider", MODELS)
def test_each_endpoint_calls_its_corresponding_tool_and_returns_its_result(
    client: TestClient,
    tool_calls: ToolCalls,
    path: str,
    module: str,
    function_name: str,
    provider: str,
) -> None:
    response = client.post(f"{PREFIX}/{path}", json={"prompt": "draw"})
    assert response.status_code == 200, response.text
    assert response.json() == tool_calls.result.model_dump(mode="json")
    expected = {**tool_calls.defaults[function_name], "prompt": "draw"}
    if provider != "volcengine":
        expected["provider"] = provider
    assert tool_calls.calls == [(function_name, expected)]
    assert all(value != threading.get_ident() for value in tool_calls.thread_ids)
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "path,provider", [(GEMINI_PATH, "laozhang"), (GPT_PATH, "evolink")]
)
def test_optional_provider_is_passed_to_the_tool(
    client: TestClient, tool_calls: ToolCalls, path: str, provider: str
) -> None:
    payload = {
        "prompt": "draw",
        "image_urls": ["https://example.com/ref.png"],
        "aspect_ratio": "16:9",
        "image_size": "2K",
    }
    if path == GPT_PATH:
        payload.update({"quality": "high", "n": 2})
    response = client.post(path, params={"provider": provider}, json=payload)
    assert response.status_code == 200, response.text
    function_name = tool_calls.calls[0][0]
    assert tool_calls.calls[0][1] == {
        **tool_calls.defaults[function_name],
        **payload,
        "provider": provider,
    }


@pytest.mark.parametrize("path", [SEEDREAM_PATH, GEMINI_PATH, GPT_PATH])
@pytest.mark.parametrize(
    "image_urls",
    [
        None,
        [],
        "https://example.com/a.png,https://example.com/b.png",
        "data:image/png;base64,aGVsbG8=",
        ["data:image/png;base64,aGVsbG8="],
    ],
)
def test_reference_parameter_shape_and_explicit_null_are_preserved(
    client: TestClient, tool_calls: ToolCalls, path: str, image_urls: object
) -> None:
    payload = {"prompt": "draw", "image_urls": image_urls}
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    assert tool_calls.calls[0][1]["image_urls"] == image_urls


@pytest.mark.parametrize(
    "path,payload",
    [
        (SEEDREAM_PATH, {"prompt": "draw", "size": "2K"}),
        (SEEDREAM_PATH, {"prompt": "draw", "watermark": False}),
        (SEEDREAM_PATH, {"prompt": "draw", "image_size": "1K"}),
        (GEMINI_PATH, {"contents": [{"parts": [{"text": "draw"}]}]}),
        (GEMINI_PATH, {"prompt": "draw", "generationConfig": {}}),
        (GEMINI_PATH, {"prompt": "draw", "image_size": "512"}),
        (GPT_PATH, {"prompt": "draw", "quality": "max"}),
        (GPT_PATH, {"prompt": "draw", "n": True}),
        (GPT_PATH, {"prompt": "draw", "stream": True}),
        (GPT_PATH, {"prompt": "draw", "output_format": "tiff"}),
        (GPT_PATH, {"prompt": "draw", "output_compression": 101}),
        (GPT_PATH, {"prompt": "draw", "safety_identifier": "x" * 129}),
        (GPT_PATH, {"prompt": "draw", "provider": "evolink"}),
        (GPT_PATH, {"prompt": "draw", "model": "gpt-image-2"}),
        (GPT_PATH, {"prompt": 123}),
        (GPT_PATH, {}),
    ],
)
def test_only_parameters_supported_by_tool_signature_are_accepted(
    client: TestClient, tool_calls: ToolCalls, path: str, payload: dict[str, object]
) -> None:
    response = client.post(path, json=payload)
    assert response.status_code == 422
    assert not tool_calls.calls


@pytest.mark.parametrize(
    "source",
    [
        "/etc/passwd",
        "../../private.txt",
        "local.png",
        "file:///etc/passwd",
        "https://user:secret@example.com/x.png",
        [1],
    ],
)
def test_reference_sources_are_passed_directly_to_the_tool(
    client: TestClient, tool_calls: ToolCalls, source: object
) -> None:
    response = client.post(
        GPT_PATH,
        json={"prompt": "private prompt", "image_urls": source},
    )
    if isinstance(source, list):
        assert response.status_code == 422
        assert not tool_calls.calls
    else:
        assert response.status_code == 200
        assert response.json() == tool_calls.result.model_dump(mode="json")
        assert tool_calls.calls[0][1]["image_urls"] == source
    assert "private prompt" not in response.text


@pytest.mark.parametrize(
    "path,provider",
    [(GPT_PATH, "google"), (GEMINI_PATH, "evolink"), (SEEDREAM_PATH, "openai")],
)
def test_channel_choices_are_restricted(
    client: TestClient, tool_calls: ToolCalls, path: str, provider: str
) -> None:
    response = client.post(path, params={"provider": provider}, json={"prompt": "draw"})
    assert response.status_code == 422
    assert not tool_calls.calls


def test_tool_failures_keep_the_unified_response(
    client: TestClient, tool_calls: ToolCalls
) -> None:
    tool_calls.result = ImageToolResponse(
        success=False, content="Upload failed", error="upload_failed", images=[]
    )
    response = client.post(GPT_PATH, json={"prompt": "draw"})
    assert response.status_code == 200
    assert response.json() == tool_calls.result.model_dump(mode="json")
    tool_calls.error = RuntimeError("private-provider-secret")
    response = client.post(GPT_PATH, json={"prompt": "draw"})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == "image_tool_failed"
    assert "private-provider-secret" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/qwen/qwen-image",
        "/openai/gpt-image-2",
        "/gpt/arbitrary",
        "/gpt/gpt-image-2.5",
        "/gemini/unknown",
    ],
)
def test_no_dynamic_or_qwen_endpoints(
    client: TestClient, tool_calls: ToolCalls, path: str
) -> None:
    assert client.post(PREFIX + path, json={"prompt": "draw"}).status_code == 404
    assert not tool_calls.calls


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Api-Key": "unrelated-client-key"},
        [("X-Api-Key", "first"), ("X-Api-Key", "second")],
        {"Authorization": "Bearer unrelated-client-key"},
    ],
)
def test_caller_authentication_headers_do_not_gate_image_tools(
    client: TestClient,
    tool_calls: ToolCalls,
    headers: dict[str, str] | list[tuple[str, str]],
) -> None:
    response = client.post(GPT_PATH, json={"prompt": "draw"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == tool_calls.result.model_dump(mode="json")
    assert len(tool_calls.calls) == 1
    assert not {"api_key", "authorization", "headers"} & tool_calls.calls[0][1].keys()


def test_asset_service_configuration_is_not_required_for_image_tools(
    client: TestClient, tool_calls: ToolCalls
) -> None:
    response = client.post(GPT_PATH, json={"prompt": "draw"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(tool_calls.calls) == 1


def test_stale_cookie_does_not_require_redis(
    auth_env: AuthTestEnvironment, tool_calls: ToolCalls
) -> None:
    auth_env.app.include_router(ai_tools_router, prefix="/api")
    storage = AsyncMock(side_effect=AssertionError("Redis was accessed"))

    async def unavailable(request: Request) -> SessionStore:
        return await storage()

    auth_env.app.dependency_overrides[get_session_store] = unavailable
    with TestClient(auth_env.app, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, "a" * 64)
        response = client.post(GPT_PATH, json={"prompt": "draw"})
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
    storage.assert_not_awaited()


@pytest.mark.parametrize(
    "source",
    [
        "http://127.0.0.1/image.png",
        "http://169.254.169.254/image.png",
        "http://[::1]/image.png",
    ],
)
def test_route_does_not_filter_image_hosts_before_calling_the_tool(
    client: TestClient, tool_calls: ToolCalls, source: str
) -> None:
    response = client.post(GPT_PATH, json={"prompt": "draw", "image_urls": source})
    assert response.status_code == 200
    assert response.json() == tool_calls.result.model_dump(mode="json")
    assert tool_calls.calls[0][1]["image_urls"] == source


@pytest.mark.parametrize("model", ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"])
@pytest.mark.parametrize("quality", ["xhigh", "max"])
def test_gpt_25_endpoint_forwards_documented_generate_and_edit_options(
    client: TestClient, tool_calls: ToolCalls, model: str, quality: str
) -> None:
    payload = {
        "prompt": "Refine this product photo",
        "image_urls": ["https://example.com/reference.png"],
        "mask_url": "https://example.com/mask.png",
        "size": "1536x1024",
        "quality": quality,
        "background": "transparent",
        "output_format": "webp",
        "output_compression": 80,
        "moderation": "auto",
        "safety_identifier": "test-user-hash",
        "n": 2,
    }
    response = client.post(f"{PREFIX}/gpt/{model}", json=payload)
    assert response.status_code == 200, response.text
    function_name, parameters = tool_calls.calls[0]
    assert parameters == {
        **tool_calls.defaults[function_name],
        **payload,
        "provider": "openai",
    }
    assert response.json() == tool_calls.result.model_dump(mode="json")
