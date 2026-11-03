"""Each fixed image model has its own route and direct tool call."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from api.routes.images import ImageRoute
from api.schemas.ai_tools import (
    Gemini3ProImageRequest,
    Gemini31FlashImageRequest,
    Gemini31FlashLiteImageRequest,
    GeminiNanoBanana21Request,
    GPTImageRequest,
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
from api.tools.images.gpt import ImageParam
from api.tools.types import ImageToolResponse

ai_tools_router = APIRouter(
    prefix="/ai-tools/images",
    tags=["ai-tools"],
    route_class=ImageRoute,
)

# Sync routes run in FastAPI's worker pool; tools can use asyncio.run for OSS.


@ai_tools_router.post(
    "/gemini/gemini-3.1-flash-lite-image", response_model=ImageToolResponse
)
async def gemini_31_flash_lite_image(
    payload: Gemini31FlashLiteImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return await gemini.image_create_with_gemini(
            prompt=payload.prompt,
            model="gemini-3.1-flash-lite-image",
            image_urls=payload.image_urls,
            aspect_ratio=payload.aspect_ratio,
            image_size=payload.image_size,
            provider=provider,
        )
    except Exception:
        return ImageToolResponse(
            image_model="gemini-3.1-flash-lite-image",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )


@ai_tools_router.post("/gemini/gemini-3-pro-image", response_model=ImageToolResponse)
async def gemini_3_pro_image(
    payload: Gemini3ProImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return await gemini.image_create_with_gemini(
            prompt=payload.prompt,
            model="gemini-3-pro-image",
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
async def gemini_31_flash_image(
    payload: Gemini31FlashImageRequest,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return await gemini.image_create_with_gemini(
            prompt=payload.prompt,
            model="gemini-3.1-flash-image",
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
async def gemini_nano_banana_21(
    payload: GeminiNanoBanana21Request,
    provider: Annotated[Literal["google", "laozhang"], Query()] = "google",
) -> ImageToolResponse:
    try:
        return await gemini.image_create_with_gemini(
            prompt=payload.prompt,
            model="gemini-nano-banana-2.1",
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
async def gpt_image_2(
    payload: GPTImageRequest,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return await gpt.image_create_with_gpt_image(
            prompt=payload.prompt,
            images=payload.image_urls,
            mask=payload.mask_url,
            model="gpt-image-2",
            image_param=ImageParam(
                action=payload.action,
                quality=payload.quality,
                background=payload.background,
                output_format=payload.output_format,
            ),
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
async def gpt_image_2_5_flare(
    payload: GPTImageRequest,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return await gpt.image_create_with_gpt_image(
            prompt=payload.prompt,
            images=payload.image_urls,
            mask=payload.mask_url,
            image_param=ImageParam(
                action=payload.action,
                quality=payload.quality,
                background=payload.background,
                output_format=payload.output_format,
            ),
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
async def gpt_image_25_sunburst(
    payload: GPTImageRequest,
    provider: Annotated[Literal["openai", "evolink"], Query()] = "openai",
) -> ImageToolResponse:
    try:
        return await gpt.image_create_with_gpt_image(
            prompt=payload.prompt,
            images=payload.image_urls,
            mask=payload.mask_url,
            model="gpt-image-2.5-sunburst",
            image_param=ImageParam(
                action=payload.action,
                quality=payload.quality,
                background=payload.background,
                output_format=payload.output_format,
            ),
        )
    except Exception:
        return ImageToolResponse(
            image_model="gpt-image-2.5-sunburst",
            success=False,
            error="image_tool_failed",
            content="Image generation or upload failed.",
            images=[],
        )
