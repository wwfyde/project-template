import base64
import importlib
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx2
import pytest
from PIL import Image
from pydantic import SecretStr

from api.tools.types import ImageInfo


@pytest.fixture
def image_upload() -> SimpleNamespace:
    output = BytesIO()
    Image.new("RGBA", (18, 12), "blue").save(output, "PNG")
    png = output.getvalue()
    metadata = ImageInfo(
        id="canonical-oss-id",
        url="https://cdn.example.test/images/canonical-oss-id.png",
        filename="canonical-oss-id.png",
        original_filename="original.png",
        storage_key="images/canonical-oss-id.png",
        mime_type="image/png",
        width=18,
        height=12,
        file_size=len(png),
        sha256="canonical-oss-hash",
    )
    return SimpleNamespace(
        png=png,
        data_url="data:image/png;base64," + base64.b64encode(png).decode("ascii"),
        metadata=metadata,
        serialized=metadata.model_dump(
            mode="json", exclude_none=True, exclude_unset=True
        ),
        upload=AsyncMock(return_value=metadata),
    )


def image_response(png: bytes) -> httpx2.Response:
    return httpx2.Response(
        200,
        content=png,
        request=httpx2.Request("GET", "https://images.example.test/result.png"),
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "seedream3",
        "qwen",
        "inpaint",
        "upscaling",
        "remove_background",
        "image_to_prompt",
    ],
)
def test_remaining_image_modules_import_without_provider_credentials(
    monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    from api.core import settings

    for provider in ("google", "volcengine", "dashscope"):
        monkeypatch.setattr(settings.providers, provider, None)
    # Importing unrelated tools must not try to load rembg or its optional runtime.
    monkeypatch.setitem(sys.modules, "rembg", None)
    module = importlib.import_module(f"api.tools.images.{module_name}")
    importlib.reload(module)


def test_seedream3_generation_reuses_canonical_oss_metadata(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace
) -> None:
    module = importlib.import_module("api.tools.images.seedream3")
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    post = Mock(
        return_value={
            "data": {
                "binary_data_base64": [
                    base64.b64encode(image_upload.png).decode("ascii")
                ]
            }
        }
    )
    monkeypatch.setattr(module, "_post_volcengine", post)

    result = module.image_create_with_seedream3(prompt="blue cup")

    assert result.success
    assert result.images == [image_upload.serialized]
    assert image_upload.upload.await_args.args[1] == image_upload.png
    assert image_upload.upload.await_args.kwargs["prefix"] == "creative/seedream"


def test_seedream3_portrait_reference_uses_metadata_url(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace
) -> None:
    module = importlib.import_module("api.tools.images.seedream3")
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    run = Mock(
        return_value={
            "binary_data_base64": [base64.b64encode(image_upload.png).decode("ascii")]
        }
    )
    monkeypatch.setattr(module, "_run_async_task", run)

    result = module.image_create_with_seedream3(
        prompt="blue cup", image_urls=image_upload.data_url, mode="portrait"
    )

    assert result.success
    assert run.call_args.args[0]["image_input"] == image_upload.metadata.url
    assert image_upload.upload.await_count == 2
    assert result.images == [image_upload.serialized]


@pytest.mark.parametrize("edit", [False, True])
def test_qwen_uploads_output_and_local_reference_with_canonical_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    image_upload: SimpleNamespace,
    edit: bool,
) -> None:
    module = importlib.import_module("api.tools.images.qwen")
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            providers=SimpleNamespace(
                dashscope=SimpleNamespace(api_key=SecretStr("qwen-key"))
            ),
            data_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    download = Mock(return_value=image_response(image_upload.png))
    if edit:
        reference = tmp_path / "reference.png"
        reference.write_bytes(image_upload.png)
        call = Mock(
            return_value=SimpleNamespace(
                status_code=200,
                output=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message={
                                "content": [
                                    {"image": "https://images.example.test/result.png"}
                                ]
                            }
                        )
                    ]
                ),
            )
        )
        monkeypatch.setattr(module.MultiModalConversation, "call", call)
        monkeypatch.setattr(module.httpx2, "get", download)
        result = module.image_edit_with_qwen(
            prompt="blue cup", image_urls=str(reference)
        )
        assert (
            call.call_args.kwargs["messages"][0]["content"][1]["image"]
            == image_upload.metadata.url
        )
        assert image_upload.upload.await_count == 2
    else:
        call = Mock(
            return_value=SimpleNamespace(
                status_code=200,
                output=SimpleNamespace(
                    results=[
                        SimpleNamespace(url="https://images.example.test/result.png")
                    ]
                ),
            )
        )
        monkeypatch.setattr(module.ImageSynthesis, "call", call)
        monkeypatch.setattr(module.requests, "get", download)
        result = module.image_generate_with_qwen(prompt="blue cup")
        assert image_upload.upload.await_count == 1
    assert call.call_args.kwargs["api_key"] == "qwen-key"
    assert result.success
    assert result.images == [image_upload.serialized]
    assert json.loads(result.content) == image_upload.serialized


@pytest.mark.parametrize("module_name", ["inpaint", "upscaling"])
def test_seedream_editing_tools_reuse_canonical_metadata_and_configuration(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace, module_name: str
) -> None:
    module = importlib.import_module(f"api.tools.images.{module_name}")
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            providers=SimpleNamespace(
                volcengine=SimpleNamespace(
                    base_url="https://ark.example.test/api/v3",
                    api_key=SecretStr("ark-key"),
                )
            )
        ),
    )
    post = Mock(
        return_value=httpx2.Response(
            200, json={"data": [{"url": "https://images.example.test/result.png"}]}
        )
    )
    monkeypatch.setattr(module.httpx2, "post", post)
    monkeypatch.setattr(
        module.httpx2, "get", Mock(return_value=image_response(image_upload.png))
    )
    kwargs = {"prompt": "blue cup", "image_url": image_upload.data_url}
    if module_name == "inpaint":
        kwargs["mask_url"] = image_upload.data_url
    result = getattr(module, f"image_{module_name}_with_seedream")(**kwargs)

    assert result.success
    assert result.images == [image_upload.serialized]
    assert post.call_args.args == (
        "https://ark.example.test/api/v3/images/generations",
    )
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer ark-key"
    assert image_upload.upload.await_args.args[1] == image_upload.png


@pytest.mark.parametrize("module_name", ["inpaint", "upscaling"])
def test_gemini_editing_tools_use_lazy_client_and_canonical_upload(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace, module_name: str
) -> None:
    module = importlib.import_module(f"api.tools.images.{module_name}")
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    part = SimpleNamespace(inline_data=SimpleNamespace(data=image_upload.png))
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.return_value = SimpleNamespace(parts=[part])
    create_client = Mock(return_value=client)
    monkeypatch.setattr(module, "_create_client", create_client)
    monkeypatch.setattr(module, "_image_part", Mock(return_value=part))
    kwargs = {"prompt": "blue cup", "image_url": image_upload.data_url}
    if module_name == "inpaint":
        kwargs["mask_url"] = image_upload.data_url
    result = getattr(module, f"image_{module_name}_with_gemini")(**kwargs)

    assert result.success
    assert result.images == [image_upload.serialized]
    assert image_upload.upload.await_args.args[1] == image_upload.png
    create_client.assert_called_once_with("google")
    client.__exit__.assert_called_once()


def test_background_removal_loads_optional_rembg_only_when_called(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace
) -> None:
    module = importlib.import_module("api.tools.images.remove_background")
    remove = Mock(return_value=image_upload.png)
    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(remove=remove))
    monkeypatch.setattr(module, "upload_image", image_upload.upload)
    monkeypatch.setattr(
        module.httpx2, "get", Mock(return_value=image_response(image_upload.png))
    )

    result = module.rembg_with_url("https://images.example.test/source.png")

    assert result is image_upload.metadata
    remove.assert_called_once_with(image_upload.png, force_return_bytes=True)
    assert image_upload.upload.await_args.args[1] == image_upload.png


@pytest.mark.asyncio
async def test_image_to_prompt_resolves_google_configuration_at_call_time(
    monkeypatch: pytest.MonkeyPatch, image_upload: SimpleNamespace
) -> None:
    module = importlib.import_module("api.tools.images.image_to_prompt")
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            providers=SimpleNamespace(google=SimpleNamespace(model="vision-model"))
        ),
    )
    client = MagicMock()
    async_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=AsyncMock(return_value=SimpleNamespace(text="blue cup"))
        )
    )
    client.aio.__aenter__.return_value = async_client
    monkeypatch.setattr(module, "_create_client", Mock(return_value=client))

    result = await module.image_to_prompt(image_upload.data_url)

    assert result == "blue cup"
    assert (
        async_client.models.generate_content.await_args.kwargs["model"]
        == "vision-model"
    )
    client.close.assert_called_once()
