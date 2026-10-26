from pathlib import Path

from pydantic import Field, SecretStr, model_validator

from api.images.contracts import StrictModel


class ImageServiceClient(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    keys: list[SecretStr] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_keys(self) -> "ImageServiceClient":
        if any(
            not 32 <= len(key.get_secret_value()) <= 512
            or not all(33 <= ord(c) <= 126 for c in key.get_secret_value())
            for key in self.keys
        ):
            raise ValueError("Image API keys require 32–512 visible ASCII characters")
        return self


class VeImageXConfig(StrictModel):
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    service_id: str | None = None
    region: str = "cn-north-1"
    domain: str | None = None
    template: str | None = None


class ImagesConfig(StrictModel):
    max_upload_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024
    )
    max_pixels: int = Field(default=16_000_000, ge=1, le=32_000_000)
    max_concurrent_edits: int = Field(default=2, ge=1, le=16)
    edit_timeout_seconds: int = Field(default=180, ge=1, le=600)
    font_path: Path | None = None
    clients: list[ImageServiceClient] = Field(default_factory=list, max_length=100)
    gpt_models: list[str] = Field(
        default_factory=lambda: ["gpt-image-2.5-sunburst", "gpt-image-2.5-flare"],
        min_length=1,
    )
    gemini_models: list[str] = Field(
        default_factory=lambda: ["gemini-3.1-flash-image"], min_length=1
    )
    seedream_models: list[str] = Field(
        default_factory=lambda: ["doubao-seedream-5-0-pro-260628"], min_length=1
    )
    veimagex: VeImageXConfig = Field(default_factory=VeImageXConfig)

    @model_validator(mode="after")
    def unique_clients(self) -> "ImagesConfig":
        ids = [client.id for client in self.clients]
        keys = [
            key.get_secret_value() for client in self.clients for key in client.keys
        ]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("Image API client IDs and credentials must be unique")
        return self
