import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

type GPTModel = Literal[
    "gpt-6.1-sol",
    "gpt-6.1-terra",
]
type GPTImageModel = Literal[
    "gpt-image-2",
    "gpt-image-2.5-sunburst",
    "gpt-image-2.5-flare",
]
type GeminiImageModel = Literal[
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image",
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
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


class ImageToolResponse(BaseModel):
    image_model: str | None = None
    content: str = Field()
    input_params: dict | None = None
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
