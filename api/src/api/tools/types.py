import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from api.tools.images.types import GeminiImageGenerationParams
from api.tools.images.types import GeminiImageModel as GeminiImageModel

__all__ = [
    "GPTModel",
    "GPTImageModel",
    "GeminiImageModel",
    "ToolResponse",
    "ImageInfo",
    "SeedreamUsage",
    "GPTImageGenerationParams",
    "GeminiImageGenerationParams",
    "ImageToolResponse",
]

type GPTModel = Literal[
    "gpt-6.1-sol",
    "gpt-6.1-terra",
]
type GPTImageModel = Literal[
    "gpt-image-2",
    "gpt-image-2.5-sunburst",
    "gpt-image-2.5-flare",
]


class ToolResponse(BaseModel):
    content: str = Field()


class ImageInfo(BaseModel):
    # index: int = 1
    url: str
    id: uuid.UUID | str
    filename: str
    original_filename: str | None = None
    file_size: int | None = None
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    image_format: Literal["png", "jpg", "webp"] | None = None
    width: int | None = None
    height: int | None = None
    content: str | None = None
    storage_key: str | None = None
    sha256: str | None = None

    @property
    def size(self) -> tuple[int, int]:
        """Python 代码中使用的便捷属性"""
        if self.width and self.height:
            return self.width, self.height
        return 0, 0

    @field_serializer("file_size")
    def serialize_file_size(self, value: int | None) -> str | None:
        if value is None:
            return None

        if value < 1024 * 1024:
            return f"{value / 1024:.2f}KB"
        return f"{value / 1024 / 1024:.2f}MB"


class SeedreamUsage:
    # https://www.volcengine.com/docs/82379/1541523?lang=zh
    generated_images: int
    output_tokens: int
    total_tokens: int


class GPTImageGenerationParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str | None = Field(
        default=None, description="改写后的生成提示词；未返回时使用原始提示词"
    )
    images: list[str] | None = Field(
        default=None, description="工具返回的输入图片引用；未返回时为空"
    )
    model: GPTImageModel | None = None
    action: str | None = None
    size: str | None = None
    quality: str | None = None
    background: str | None = None
    output_format: str | None = None
    output_compression: int | None = None
    input_fidelity: str | None = None
    moderation: str | None = None
    partial_images: int | None = None
    input_image_mask: dict[str, str] | None = None
    id: str | None = None
    type: str | None = None
    status: str | None = None
    error: dict | None = None
    calls: list["GPTImageGenerationParams"] | None = None


class ImageToolResponse(BaseModel):
    image_model: str | None = None
    content: str = Field()
    generation_params: GPTImageGenerationParams | GeminiImageGenerationParams | None = (
        None
    )
    instructions: str | None = None
    success: bool = True
    error: str | None = None
    images: list[dict] | None = None
    usage: dict | None = None
    data: dict | None = None


if __name__ == "__main__":
    image_info = ImageInfo(
        file_size=12123234,
        url="https://cdn.fullspeed.cn/creative/gemini/019d0539-e153-7880-8326-6c5c1f04bbc7.png",
        id=str(uuid.uuid7()),
        filename="gemini.png",
        mime_type="image/png",
    )
    print(image_info.model_dump(exclude_unset=True))
