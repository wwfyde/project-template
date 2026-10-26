"""Explicit request parameters maintained separately for each image endpoint."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Gemini25FlashImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: (
        Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"] | None
    ) = None
    image_size: Literal["1K", "2K", "4K"] | None = "1K"


class Gemini3ProImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: (
        Literal["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"] | None
    ) = None
    image_size: Literal["1K", "2K", "4K"] | None = None


class Gemini31FlashImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: (
        Literal[
            "auto",
            "1:1",
            "2:3",
            "3:2",
            "3:4",
            "4:3",
            "4:5",
            "5:4",
            "9:16",
            "16:9",
            "1:8",
            "8:1",
            "21:9",
        ]
        | None
    ) = None
    image_size: Literal["1K", "2K", "4K"] | None = None


class GeminiNanoBanana21Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: (
        Literal[
            "auto",
            "1:1",
            "2:3",
            "3:2",
            "3:4",
            "4:3",
            "4:5",
            "5:4",
            "9:16",
            "16:9",
            "1:8",
            "8:1",
            "21:9",
        ]
        | None
    ) = None
    image_size: Literal["1K", "2K", "4K"] | None = None


class Seedream40Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["1K", "2K", "4K"] | None = "2K"


class Seedream45Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["2K", "4K"] | None = "2K"


class Seedream50LiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["2K", "4K"] | None = "2K"


class Seedream50ProRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["1K", "2K", "4K"] | None = "2K"


class GPTImage2Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["1K", "2K", "4K"] | None = None
    quality: Literal["low", "medium", "high", "auto"] = "low"
    n: int = 1
    size: str | None = None
    background: Literal["auto", "opaque", "transparent"] | None = None
    output_format: Literal["png", "jpeg", "webp"] | None = None
    output_compression: int | None = Field(default=None, ge=0, le=100)
    moderation: Literal["auto", "low"] | None = None
    safety_identifier: str | None = Field(default=None, max_length=128)
    mask_url: str | None = None


class GPTImage25FlareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["1K", "2K", "4K"] | None = None
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low"
    n: int = 1
    size: str | None = None
    background: Literal["auto", "opaque", "transparent"] | None = None
    output_format: Literal["png", "jpeg", "webp"] | None = None
    output_compression: int | None = Field(default=None, ge=0, le=100)
    moderation: Literal["auto", "low"] | None = None
    safety_identifier: str | None = Field(default=None, max_length=128)
    mask_url: str | None = None


class GPTImage25SunburstRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    prompt: str
    image_urls: str | list[str] | None = None
    aspect_ratio: str | None = None
    image_size: Literal["1K", "2K", "4K"] | None = None
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "low"
    n: int = 1
    size: str | None = None
    background: Literal["auto", "opaque", "transparent"] | None = None
    output_format: Literal["png", "jpeg", "webp"] | None = None
    output_compression: int | None = Field(default=None, ge=0, le=100)
    moderation: Literal["auto", "low"] | None = None
    safety_identifier: str | None = Field(default=None, max_length=128)
    mask_url: str | None = None
