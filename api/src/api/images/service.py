import asyncio
import logging
from collections.abc import Callable
from pathlib import PurePath
from typing import Literal

from api.images.config import ImagesConfig
from api.images.contracts import (
    CommentCreate,
    EditRequest,
    ImageAsset,
    ImageComment,
    ImageFailure,
    ImageProvider,
    ImageStore,
    ProviderInfo,
    ProviderInput,
)
from api.images.processing import (
    finish_provider_edit,
    local_edit,
    normalize_image,
    validate_mask,
)

logger = logging.getLogger(__name__)


async def _process[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    # Cancelling a thread await does not stop Pillow. Retain the caller's capacity
    # slot until the bounded CPU operation actually finishes.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


class ImageService:
    def __init__(
        self,
        store: ImageStore,
        providers: dict[str, ImageProvider],
        config: ImagesConfig,
    ) -> None:
        self.store, self.providers, self.config = store, providers, config
        self._edits = asyncio.Semaphore(config.max_concurrent_edits)

    def provider_info(self) -> list[ProviderInfo]:
        return [
            ProviderInfo(
                id="local",
                label="Local",
                configured=True,
                operations=["markup", "resize"],
            ),
            *[
                provider.info.model_copy(deep=True)
                for provider in self.providers.values()
                if provider.info.id != "local"
            ],
        ]

    async def upload(
        self,
        owner: str,
        content: bytes,
        filename: str,
        purpose: Literal["image", "mask"] = "image",
    ) -> ImageAsset:
        if self._edits.locked():
            raise ImageFailure(
                "image_service_busy",
                "Image processing capacity is busy. Try again later.",
                429,
            )
        async with self._edits:
            normalized, width, height = await _process(
                normalize_image, content, self.config
            )
        stem = PurePath(filename.replace("\\", "/")).stem[:120]
        stem = (
            "".join(char for char in stem if ord(char) >= 32 and ord(char) != 127)
            or "image"
        )
        asset = ImageAsset(
            filename=f"{stem}.png", width=width, height=height, purpose=purpose
        )
        await self.store.create_asset(owner, asset, normalized)
        return asset

    async def edit(self, owner: str, asset_id: str, request: EditRequest) -> ImageAsset:
        source_asset = await self.store.get_asset(owner, asset_id)
        if self._edits.locked():
            raise ImageFailure(
                "image_service_busy",
                "Image processing capacity is busy. Try again later.",
                429,
            )
        async with self._edits:
            content = await self.store.get_content(owner, asset_id)
            model = None
            if request.operation in {"markup", "resize"}:
                if request.provider != "local":
                    raise ImageFailure(
                        "unsupported_operation",
                        "Markup and resize use the local provider.",
                        422,
                    )
                output, width, height = await _process(
                    local_edit, content, request, self.config
                )
            else:
                provider = self.providers.get(request.provider)
                if (
                    provider is None
                    or request.operation not in provider.info.operations
                ):
                    raise ImageFailure(
                        "unsupported_operation",
                        "The selected provider does not support this operation.",
                        422,
                    )
                if not provider.info.configured:
                    raise ImageFailure(
                        "provider_unavailable",
                        "The selected image provider is not configured.",
                        503,
                    )
                model = request.model or provider.info.default_model
                if not model or model not in provider.info.models:
                    raise ImageFailure(
                        "unsupported_model",
                        "Select a model from the provider's advertised models.",
                        422,
                    )
                mask = None
                if request.mask_asset_id:
                    mask_content = await self.store.get_content(
                        owner, request.mask_asset_id
                    )
                    mask = await _process(
                        validate_mask,
                        mask_content,
                        (source_asset.width, source_asset.height),
                        self.config,
                    )
                provider_request = ProviderInput(
                    operation=request.operation,
                    model=model,
                    image=content,
                    mask=mask,
                    prompt=request.prompt,
                )
                try:
                    async with asyncio.timeout(self.config.edit_timeout_seconds):
                        generated = await provider.edit(provider_request)
                        output, width, height = await _process(
                            finish_provider_edit, content, generated, mask, self.config
                        )
                except TimeoutError as error:
                    raise ImageFailure(
                        "provider_timeout",
                        "Image provider timed out. A remote charge may still have occurred; requests are not retried automatically.",
                        504,
                    ) from error
                except ImageFailure:
                    raise
                except Exception as error:
                    logger.warning(
                        "Image provider failed: provider=%s error_type=%s",
                        request.provider,
                        type(error).__name__,
                    )
                    raise ImageFailure(
                        "provider_failed",
                        "Image provider could not complete the edit.",
                        502,
                    ) from error
            asset = ImageAsset(
                filename=source_asset.filename,
                width=width,
                height=height,
                parent_id=source_asset.id,
                operation=request.operation,
                provider=request.provider,
                model=model,
            )
            await self.store.create_asset(owner, asset, output)
            return asset

    async def comment(
        self, owner: str, asset_id: str, request: CommentCreate
    ) -> ImageComment:
        comment = ImageComment(asset_id=asset_id, **request.model_dump())
        await self.store.add_comment(owner, comment)
        return comment
