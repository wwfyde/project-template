from urllib.request import urlopen

from pydantic import BaseModel, Field


class DataURL(BaseModel):
    """Structured representation of a parsed data URL."""

    mime_type: str = Field(description="")
    charset: str | None = Field(default=None, description="charset 参数, 没有则为 None")
    params: dict[str, str] = Field(
        default_factory=dict, description="mediatype 的其余参数"
    )
    is_base64: bool = Field(description="原始 URL 是否使用 ;base64 编码")
    data: bytes = Field(description="解码后的原始字节")


def decode_data_url(data_url: str) -> bytes:
    """Decode a valid RFC 2397 Data URL."""
    if not data_url.startswith("data:"):
        raise ValueError("Invalid data URL scheme")
    with urlopen(data_url) as response:
        return response.read()
