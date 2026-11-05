from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type GeminiImageModel = Literal[
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
]


class GeminiImageGenerationParams(BaseModel):
    """Submitted Gemini generation settings and the returned model version."""

    model_config = ConfigDict(extra="allow")

    model: GeminiImageModel
    model_version: str | None = None
    provider: Literal["google", "laozhang"] | None = None
    prompt: str | None = None
    images: list[str] | None = Field(
        default=None, description="提交的参考图片 URL、data URL 或文件路径"
    )

    # Fields exposed by google.genai.types.ImageConfig.
    aspect_ratio: str | None = None
    image_size: str | None = None
    person_generation: str | None = None
    prominent_people: str | None = None
    output_mime_type: str | None = None
    output_compression_quality: int | None = None
    image_output_options: dict | None = None

    response_modalities: list[str] | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: float | None = None
    candidate_count: int | None = None
    seed: int | None = None
    max_output_tokens: int | None = None
    thinking_config: dict | None = None
    safety_settings: list[dict] | None = None
