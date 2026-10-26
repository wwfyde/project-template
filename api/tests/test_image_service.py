"""Image output and dispatch invariants without paid model calls."""

import asyncio
import threading
from io import BytesIO

import pytest
from PIL import Image

from api.images.config import ImagesConfig
from api.images.contracts import (
    CommentCreate,
    EditRequest,
    ImageFailure,
    ProviderInfo,
    ProviderInput,
)
from api.images.processing import normalize_image
from api.images.service import ImageService
from api.images.store import InMemoryImageStore


def png(color: str | tuple, size: tuple[int, int] = (20, 10)) -> bytes:
    data = BytesIO()
    Image.new("RGBA", size, color).save(data, format="PNG")
    return data.getvalue()


class FakeProvider:
    def __init__(self) -> None:
        self.info = ProviderInfo(
            id="gpt",
            label="GPT",
            configured=True,
            models=["test-model"],
            default_model="test-model",
            operations=["erase", "remove_background"],
            mask_mode="native",
        )
        self.requests: list[ProviderInput] = []
        self.output = png("blue")
        self.error: Exception | None = None
        self.wait = False

    async def edit(self, request: ProviderInput) -> bytes:
        self.requests.append(request)
        if self.wait:
            await asyncio.Event().wait()
        if self.error:
            raise self.error
        return self.output


@pytest.fixture
def service() -> ImageService:
    return ImageService(InMemoryImageStore(), {"gpt": FakeProvider()}, ImagesConfig())


@pytest.mark.asyncio
async def test_upload_and_resize_are_immutable_and_contain_uses_transparent_padding(
    service: ImageService,
) -> None:
    source = await service.upload("owner", png("red"), "../../private.jpg")
    resized = await service.edit(
        "owner", source.id, EditRequest(operation="resize", width=20, height=20)
    )
    assert resized.parent_id == source.id
    assert resized.filename == "private.png"
    assert resized.provider == "local"
    assert (resized.width, resized.height) == (20, 20)
    result = Image.open(BytesIO(await service.store.get_content("owner", resized.id)))
    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((10, 10)) == (255, 0, 0, 255)
    assert await service.store.get_content("owner", source.id) == png("red")


@pytest.mark.asyncio
@pytest.mark.parametrize("fit", ["cover", "stretch"])
async def test_resize_dimensions_and_opaque_output(
    service: ImageService, fit: str
) -> None:
    source = await service.upload("owner", png("red"), "source")
    edited = await service.edit(
        "owner",
        source.id,
        EditRequest(operation="resize", width=13, height=19, fit=fit),
    )
    image = Image.open(BytesIO(await service.store.get_content("owner", edited.id)))
    assert image.size == (13, 19)
    assert image.getchannel("A").getextrema() == (255, 255)


@pytest.mark.asyncio
async def test_markup_coordinates_and_comments_do_not_call_a_model(
    service: ImageService,
) -> None:
    source = await service.upload("owner", png("white"), "source")
    edited = await service.edit(
        "owner",
        source.id,
        EditRequest(
            operation="markup",
            markup=[
                {
                    "kind": "path",
                    "points": [{"x": 0.5, "y": 0.5}],
                    "color": "#ff0000",
                    "width": 2,
                }
            ],
        ),
    )
    image = Image.open(BytesIO(await service.store.get_content("owner", edited.id)))
    assert image.getpixel((10, 4)) == (255, 0, 0, 255)
    comment = await service.comment(
        "owner", source.id, CommentCreate(text="  Change headline  ", x=0.2, y=0.3)
    )
    assert comment.text == "Change headline"
    assert service.providers["gpt"].requests == []
    assert len(await service.store.list_assets("owner", 10)) == 2


@pytest.mark.asyncio
async def test_erase_preserves_every_unselected_pixel_and_passes_white_mask(
    service: ImageService,
) -> None:
    source = await service.upload("owner", png("red"), "source")
    selection = Image.new("RGB", (20, 10), "black")
    selection.paste("white", (0, 0, 5, 5))
    data = BytesIO()
    selection.save(data, "PNG")
    mask = await service.upload("owner", data.getvalue(), "mask", "mask")
    # Simulate a provider producing a completely altered, differently sized image.
    service.providers["gpt"].output = png("blue", (40, 20))
    edited = await service.edit(
        "owner",
        source.id,
        EditRequest(operation="erase", provider="gpt", mask_asset_id=mask.id),
    )
    result = Image.open(BytesIO(await service.store.get_content("owner", edited.id)))
    assert result.size == (20, 10)
    for x in range(20):
        for y in range(10):
            assert result.getpixel((x, y)) == (
                (0, 0, 255, 255) if x < 5 and y < 5 else (255, 0, 0, 255)
            )
    request = service.providers["gpt"].requests[0]
    assert request.model == "test-model"
    assert Image.open(BytesIO(request.mask)).getpixel((0, 0)) == 255
    assert len(await service.store.list_assets("owner", 10)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["foreign", "size", "empty", "transparent"])
async def test_invalid_mask_rejected_before_provider_call(
    service: ImageService, kind: str
) -> None:
    source = await service.upload("owner", png("red"), "source")
    mask = await service.upload(
        "other" if kind == "foreign" else "owner",
        png(
            (255, 255, 255, 0)
            if kind == "transparent"
            else "black"
            if kind == "empty"
            else "white",
            (2, 2) if kind == "size" else (20, 10),
        ),
        "mask",
        "mask",
    )
    with pytest.raises(ImageFailure) as error:
        await service.edit(
            "owner",
            source.id,
            EditRequest(operation="erase", provider="gpt", mask_asset_id=mask.id),
        )
    assert error.value.status == (404 if kind == "foreign" else 422)
    assert service.providers["gpt"].requests == []


@pytest.mark.asyncio
async def test_foreign_source_cannot_invoke_a_paid_provider(
    service: ImageService,
) -> None:
    source = await service.upload("other", png("red"), "source")
    with pytest.raises(ImageFailure) as error:
        await service.edit(
            "owner",
            source.id,
            EditRequest(operation="remove_background", provider="gpt"),
        )
    assert error.value.status == 404
    assert service.providers["gpt"].requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["unconfigured", "unknown-model", "local", "unsupported"]
)
async def test_dispatch_rejects_unavailable_or_unsupported_choices(
    service: ImageService, bad: str
) -> None:
    source = await service.upload("owner", png("red"), "source")
    provider = service.providers["gpt"]
    if bad == "unconfigured":
        provider.info.configured = False
    if bad == "unsupported":
        provider.info.operations = ["erase"]
    with pytest.raises(ImageFailure):
        await service.edit(
            "owner",
            source.id,
            EditRequest(
                operation="remove_background",
                provider="local" if bad == "local" else "gpt",
                model="arbitrary-paid-model" if bad == "unknown-model" else None,
            ),
        )
    assert provider.requests == []


@pytest.mark.asyncio
async def test_background_removal_requires_real_alpha(service: ImageService) -> None:
    source = await service.upload("owner", png("red"), "source")
    with pytest.raises(ImageFailure, match="transparent cutout"):
        await service.edit(
            "owner",
            source.id,
            EditRequest(operation="remove_background", provider="gpt"),
        )
    provider = service.providers["gpt"]
    cutout = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    cutout.paste("red", (5, 2, 15, 8))
    data = BytesIO()
    cutout.save(data, "PNG")
    provider.output = data.getvalue()
    edited = await service.edit(
        "owner", source.id, EditRequest(operation="remove_background", provider="gpt")
    )
    assert (
        Image.open(
            BytesIO(await service.store.get_content("owner", edited.id))
        ).getpixel((0, 0))[3]
        == 0
    )


@pytest.mark.asyncio
async def test_private_provider_errors_and_timeouts_are_safe_and_never_saved(
    service: ImageService,
) -> None:
    source = await service.upload("owner", png("red"), "source")
    provider = service.providers["gpt"]
    provider.error = RuntimeError("secret-key-and-private-image")
    with pytest.raises(ImageFailure) as error:
        await service.edit(
            "owner",
            source.id,
            EditRequest(operation="remove_background", provider="gpt"),
        )
    assert error.value.code == "provider_failed"
    assert "secret" not in error.value.message
    provider.error = None
    provider.wait = True
    service.config.edit_timeout_seconds = 0.01
    with pytest.raises(ImageFailure) as error:
        await service.edit(
            "owner",
            source.id,
            EditRequest(operation="remove_background", provider="gpt"),
        )
    assert error.value.status == 504
    assert len(provider.requests) == 2
    assert len(await service.store.list_assets("owner", 10)) == 1


@pytest.mark.asyncio
async def test_processor_capacity_limits_upload_and_edits(
    service: ImageService,
) -> None:
    source = await service.upload("owner", png("red"), "source")
    service._edits = asyncio.Semaphore(1)
    async with service._edits:
        with pytest.raises(ImageFailure) as upload_error:
            await service.upload("owner", png("red"), "source")
        assert upload_error.value.status == 429
        with pytest.raises(ImageFailure) as edit_error:
            await service.edit(
                "owner", source.id, EditRequest(operation="resize", width=2, height=2)
            )
        assert edit_error.value.status == 429


@pytest.mark.parametrize(
    "content", [b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", b"not an image"]
)
def test_rejects_untrusted_formats(content: bytes) -> None:
    with pytest.raises(ImageFailure):
        normalize_image(content, ImagesConfig())


def test_pixel_budget_checked_before_decode() -> None:
    with pytest.raises(ImageFailure) as error:
        normalize_image(png("red", (20, 20)), ImagesConfig(max_pixels=10))
    assert error.value.status == 413


def test_jpeg_orientation_applied_and_exif_stripped() -> None:
    source = Image.new("RGB", (20, 10), "red")
    exif = source.getexif()
    exif[274] = 6
    buffer = BytesIO()
    source.save(buffer, "JPEG", exif=exif)
    content, width, height = normalize_image(buffer.getvalue(), ImagesConfig())
    assert (width, height) == (10, 20)
    assert not Image.open(BytesIO(content)).getexif()


@pytest.mark.asyncio
async def test_cancelled_upload_keeps_capacity_until_decoder_finishes(
    service: ImageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.images import service as module

    entered, release = threading.Event(), threading.Event()

    def decode(content: bytes, config: ImagesConfig) -> tuple[bytes, int, int]:
        entered.set()
        assert release.wait(2)
        return content, 20, 10

    monkeypatch.setattr(module, "normalize_image", decode)
    service._edits = asyncio.Semaphore(1)
    pending = asyncio.create_task(service.upload("owner", png("red"), "source"))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        pending.cancel()
        await asyncio.sleep(0)
        with pytest.raises(ImageFailure) as error:
            await service.upload("owner", png("red"), "second")
        assert error.value.status == 429
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not service._edits.locked()
