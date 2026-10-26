import base64
import importlib
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import httpx2
import pytest
from PIL import Image
from pydantic import SecretStr

from api.tools.types import ImageInfo, ImageToolResponse

TOOLS = [
    ("seedream", "image_create_with_seedream", "doubao-seedream-4-0-250828"),
    ("seedream4_5", "image_create_with_seedream4_5", "doubao-seedream-4-5-251128"),
    (
        "seedream5_lite",
        "image_create_with_seedream5_lite",
        "doubao-seedream-5-0-260128",
    ),
    (
        "seedream5_pro",
        "image_create_with_seedream5_pro",
        "doubao-seedream-5-0-pro-260628",
    ),
]


@pytest.fixture(params=TOOLS, ids=[item[0] for item in TOOLS])
def image_tool(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[SimpleNamespace]:
    module_name, function_name, model = request.param
    module: ModuleType = importlib.import_module(f"api.tools.images.{module_name}")
    output = BytesIO()
    Image.new("RGBA", (12, 8), (30, 90, 170, 128)).save(output, "PNG")
    png = output.getvalue()
    config = SimpleNamespace(
        providers=SimpleNamespace(
            volcengine=SimpleNamespace(
                base_url="https://ark.example.test/api/v3/",
                api_key=SecretStr("seedream-test-key"),
            )
        ),
        data_dir=tmp_path,
    )
    monkeypatch.setattr(module, "settings", config)
    state = SimpleNamespace(
        module=module,
        call=getattr(module, function_name),
        model=model,
        png=png,
        config=config,
        requests=[],
        uploads=[],
        status=200,
        images=[{"url": "https://output.example.test/generated.png"}],
    )

    def upstream(request: httpx2.Request) -> httpx2.Response:
        state.requests.append(request)
        if request.method == "POST":
            return httpx2.Response(
                state.status,
                json={"data": state.images, "usage": {"generated_images": 1}},
            )
        assert str(request.url) == "https://output.example.test/generated.png"
        return httpx2.Response(200, content=png)

    async def upload(filename: str, data: bytes, **kwargs: object) -> ImageInfo:
        with Image.open(BytesIO(data)) as image:
            assert image.format == "PNG"
            width, height = image.size
        identifier = f"oss-id-{len(state.uploads) + 1}"
        storage_key = f"{kwargs['prefix']}/{identifier}.png"
        metadata = ImageInfo(
            id=identifier,
            url=f"https://cdn.example.test/{storage_key}",
            filename=f"{identifier}.png",
            original_filename=filename,
            storage_key=storage_key,
            mime_type="image/png",
            width=width,
            height=height,
            file_size=len(data),
            sha256="hash-from-oss-uploader",
        )
        state.uploads.append((data, kwargs, metadata))
        return metadata

    monkeypatch.setattr(module, "upload_image", upload)
    monkeypatch.setattr(
        module.requests,
        "get",
        Mock(side_effect=AssertionError("Unexpected reference download")),
    )
    with httpx2.Client(transport=httpx2.MockTransport(upstream)) as client:
        monkeypatch.setattr(module.httpx2, "post", client.post)
        monkeypatch.setattr(module.httpx2, "get", client.get)
        yield state


def test_seedream_uploads_generated_bytes_and_keeps_oss_metadata(
    image_tool: SimpleNamespace,
) -> None:
    import json

    result = image_tool.call(prompt="a blue cup", aspect_ratio="3:2", image_size="2K")

    assert isinstance(result, ImageToolResponse)
    assert result.success
    assert result.image_model == image_tool.model
    assert result.usage == {"generated_images": 1}
    generation = image_tool.requests[0]
    assert str(generation.url) == "https://ark.example.test/api/v3/images/generations"
    assert generation.headers["Authorization"] == "Bearer seedream-test-key"
    assert json.loads(generation.content)["model"] == image_tool.model
    assert json.loads(generation.content)["size"] == "2496x1664"
    data, options, metadata = image_tool.uploads[0]
    assert data == image_tool.png
    assert options == {"prefix": "creative/seedream"}
    assert result.images == [
        metadata.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    ]
    assert result.images[0]["id"] == "oss-id-1"
    assert result.images[0]["storage_key"] == "creative/seedream/oss-id-1.png"


def test_seedream_single_data_url_keeps_its_base64_comma(
    image_tool: SimpleNamespace,
) -> None:
    import json

    reference = "data:image/png;base64," + base64.b64encode(image_tool.png).decode(
        "ascii"
    )
    result = image_tool.call(prompt="make the cup blue", image_urls=reference)

    assert result.success
    assert json.loads(image_tool.requests[0].content)["image"] == [reference]
    assert len(image_tool.uploads) == 1


@pytest.mark.parametrize("absolute", [False, True])
def test_seedream_local_reference_uses_uploaded_metadata_url(
    image_tool: SimpleNamespace, absolute: bool
) -> None:
    import json

    directory = image_tool.config.data_dir / "files"
    directory.mkdir()
    reference = directory / "reference.png"
    reference.write_bytes(image_tool.png)
    result = image_tool.call(
        prompt="make the cup blue",
        image_urls=str(reference) if absolute else reference.name,
    )

    assert result.success
    assert len(image_tool.uploads) == 2
    uploaded_reference = image_tool.uploads[0][2]
    assert json.loads(image_tool.requests[0].content)["image"] == [
        uploaded_reference.url
    ]
    assert image_tool.uploads[0][1] == {"prefix": "files"}
    assert result.images[0]["id"] == "oss-id-2"
    assert result.images[0]["url"] == image_tool.uploads[1][2].url


@pytest.mark.parametrize("failure", ["configuration", "reference", "upstream", "empty"])
def test_seedream_returns_tool_failure_for_setup_and_provider_errors(
    image_tool: SimpleNamespace, failure: str
) -> None:
    kwargs = {}
    if failure == "configuration":
        image_tool.config.providers.volcengine = None
    elif failure == "reference":
        kwargs["image_urls"] = "missing.png"
    elif failure == "upstream":
        image_tool.status = 503
    else:
        image_tool.images = []

    result = image_tool.call(prompt="a blue cup", **kwargs)

    assert isinstance(result, ImageToolResponse)
    assert result.success is False
    assert result.image_model == image_tool.model
    assert not result.images
    assert not image_tool.uploads
    if failure in {"configuration", "reference"}:
        assert not image_tool.requests


def test_seedream_returns_tool_failure_when_oss_upload_fails(
    image_tool: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def upload_failure(*args: object, **kwargs: object) -> ImageInfo:
        raise RuntimeError("mock storage unavailable")

    monkeypatch.setattr(image_tool.module, "upload_image", upload_failure)
    result = image_tool.call(prompt="a blue cup")

    assert result.success is False
    assert result.image_model == image_tool.model
    assert "mock storage unavailable" not in result.content
    assert result.error == "image_tool_failed"
