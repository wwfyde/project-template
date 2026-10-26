"""Each fixed image model has its own route and direct tool call."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from api.routes.images import ImageRoute
from api.schemas.ai_tools import (
    Gemini3ProImageRequest,
    Gemini25FlashImageRequest,
    Gemini31FlashImageRequest,
    GeminiNanoBanana21Request,
    GPTImage2Request,
    GPTImage25FlareRequest,
    GPTImage25SunburstRequest,
    Seedream40Request,
    Seedream45Request,
    Seedream50LiteRequest,
    Seedream50ProRequest,
)
from api.tools.images import (
    gemini,
    gpt,
    seedream,
    seedream4_5,
    seedream5_lite,
    seedream5_pro,
)
from api.tools.types import ImageToolResponse

ai_tools_router = APIRouter(
    prefix="/ai-tools/images",
    tags=["ai-tools"],
    route_class=ImageRoute,
)

# Sync routes run in FastAPI's worker pool; tools can use asyncio.run for OSS.


@ai_tools_router.post(
    "/gemini/gemini-2.5-flash-image", response_model=ImageToolResponse
)
def gemini_25_flash_image(
    payload: Gemini25FlashImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return gemini.image_create_with_gemini_flash(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gemini-2.5-flash-image",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post("/gemini/gemini-3-pro-image", response_model=ImageToolResponse)
def gemini_3_pro_image(
    payload: Gemini3ProImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return gemini.image_create_with_gemini(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gemini-3-pro-image",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/gemini/gemini-3.1-flash-image", response_model=ImageToolResponse
)
def gemini_31_flash_image(
    payload: Gemini31FlashImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return gemini.image_create_with_gemini_flash_2(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gemini-3.1-flash-image",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/gemini/gemini-nano-banana-2.1", response_model=ImageToolResponse
)
def gemini_nano_banana_21(
    payload: GeminiNanoBanana21Request,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return gemini.image_create_with_gemini_flash_2_1(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gemini-nano-banana-2.1",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/seedream/doubao-seedream-4-0-250828", response_model=ImageToolResponse
)
def seedream_40(
    payload: Seedream40Request,
    provider: Annotated[Literal["volcengine"], Query()] = "volcengine",
) -> ImageToolResponse:
    try:
        return seedream.image_create_with_seedream(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
        )
    except Exception:
        return ImageToolResponse(
            image_model="doubao-seedream-4-0-250828",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/seedream/doubao-seedream-4-5-251128", response_model=ImageToolResponse
)
def seedream_45(
    payload: Seedream45Request,
    provider: Annotated[Literal["volcengine"], Query()] = "volcengine",
) -> ImageToolResponse:
    try:
        return seedream4_5.image_create_with_seedream4_5(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
        )
    except Exception:
        return ImageToolResponse(
            image_model="doubao-seedream-4-5-251128",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/seedream/doubao-seedream-5-0-260128", response_model=ImageToolResponse
)
def seedream_50_lite(
    payload: Seedream50LiteRequest,
    provider: Annotated[Literal["volcengine"], Query()] = "volcengine",
) -> ImageToolResponse:
    try:
        return seedream5_lite.image_create_with_seedream5_lite(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
        )
    except Exception:
        return ImageToolResponse(
            image_model="doubao-seedream-5-0-260128",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post(
    "/seedream/doubao-seedream-5-0-pro-260628", response_model=ImageToolResponse
)
def seedream_50_pro(
    payload: Seedream50ProRequest,
    provider: Annotated[Literal["volcengine"], Query()] = "volcengine",
) -> ImageToolResponse:
    try:
        return seedream5_pro.image_create_with_seedream5_pro(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
        )
    except Exception:
        return ImageToolResponse(
            image_model="doubao-seedream-5-0-pro-260628",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post("/gpt/gpt-image-2", response_model=ImageToolResponse)
def gpt_image_2(
    payload: GPTImage2Request,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return gpt.image_create_with_gpt_image_2(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
            quality=payload.quality,
            n=payload.n,
            size=payload.size,
            background=payload.background,
            output_format=payload.output_format,
            output_compression=payload.output_compression,
            moderation=payload.moderation,
            safety_identifier=payload.safety_identifier,
            mask_url=payload.mask_url,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gpt-image-2",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post("/gpt/gpt-image-2.5-flare", response_model=ImageToolResponse)
def gpt_image_25_flare(
    payload: GPTImage25FlareRequest,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return gpt.image_create_with_gpt_image_2_5_flare(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
            quality=payload.quality,
            n=payload.n,
            size=payload.size,
            background=payload.background,
            output_format=payload.output_format,
            output_compression=payload.output_compression,
            moderation=payload.moderation,
            safety_identifier=payload.safety_identifier,
            mask_url=payload.mask_url,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gpt-image-2.5-flare",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post("/gpt/gpt-image-2.5-sunburst", response_model=ImageToolResponse)
def gpt_image_25_sunburst(
    payload: GPTImage25SunburstRequest,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return gpt.image_create_with_gpt_image_2_5_sunburst(
            prompt=payload.prompt,
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
            quality=payload.quality,
            n=payload.n,
            size=payload.size,
            background=payload.background,
            output_format=payload.output_format,
            output_compression=payload.output_compression,
            moderation=payload.moderation,
            safety_identifier=payload.safety_identifier,
            mask_url=payload.mask_url,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gpt-image-2.5-sunburst",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )
