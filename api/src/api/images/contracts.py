from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Operation = Literal["markup", "remove_background", "erase", "resize"]
ProviderId = Literal["local", "gpt", "gemini", "seedream", "veimagex"]


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ImageFailure(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Point(StrictModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class Markup(StrictModel):
    kind: Literal["path", "text", "rectangle", "ellipse"]
    points: list[Point] = Field(min_length=1, max_length=2000)
    color: str = Field(default="#ef4444", pattern=r"^#[0-9a-fA-F]{6}$")
    width: int = Field(default=4, ge=1, le=128)
    text: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_shape(self) -> "Markup":
        if self.kind in {"rectangle", "ellipse"} and len(self.points) != 2:
            raise ValueError("Shapes require exactly two points")
        if self.kind == "text" and (
            len(self.points) != 1 or not self.text or not self.text.strip()
        ):
            raise ValueError("Text requires one anchor and nonempty text")
        if self.kind != "text" and self.text is not None:
            raise ValueError("Only text markup accepts text")
        return self


class EditRequest(StrictModel):
    operation: Operation
    provider: ProviderId = "local"
    model: str | None = Field(default=None, min_length=1, max_length=200)
    mask_asset_id: str | None = Field(default=None, max_length=36)
    prompt: str | None = Field(default=None, max_length=2000)
    width: int | None = Field(default=None, ge=1, le=8192)
    height: int | None = Field(default=None, ge=1, le=8192)
    fit: Literal["contain", "cover", "stretch"] = "contain"
    background: str = Field(
        default="transparent", pattern=r"^(transparent|#[0-9a-fA-F]{6})$"
    )
    markup: list[Markup] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_operation(self) -> "EditRequest":
        if self.operation == "resize" and (self.width is None or self.height is None):
            raise ValueError("Resize requires width and height")
        if self.operation != "resize" and (
            self.width is not None or self.height is not None
        ):
            raise ValueError("Dimensions only apply to resize")
        if self.operation == "erase" and self.mask_asset_id is None:
            raise ValueError("Erase requires mask_asset_id")
        if self.operation != "erase" and self.mask_asset_id is not None:
            raise ValueError("Only erase accepts a mask")
        if self.operation == "markup" and not self.markup:
            raise ValueError("Markup requires at least one item")
        if self.operation != "markup" and self.markup is not None:
            raise ValueError("Only markup accepts markup items")
        if self.markup and sum(len(item.points) for item in self.markup) > 10000:
            raise ValueError("Too many markup points")
        if self.operation in {"markup", "resize"} and (
            self.model is not None or self.prompt is not None
        ):
            raise ValueError("Local operations do not accept a model or prompt")
        return self


class ImageAsset(StrictModel):
    id: str = Field(default_factory=new_id)
    filename: str
    width: int
    height: int
    mime_type: Literal["image/png"] = "image/png"
    purpose: Literal["image", "mask"] = "image"
    parent_id: str | None = None
    operation: Operation | None = None
    provider: ProviderId | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AssetResponse(ImageAsset):
    content_url: str


class CommentCreate(Point):
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def nonempty_text(self) -> "CommentCreate":
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("Comment must not be empty")
        return self


class ImageComment(CommentCreate):
    id: str = Field(default_factory=new_id)
    asset_id: str
    created_at: datetime = Field(default_factory=utc_now)


class ProviderInfo(StrictModel):
    id: ProviderId
    label: str
    configured: bool
    models: list[str] = Field(default_factory=list)
    default_model: str | None = None
    operations: list[Operation]
    mask_mode: Literal["native", "reference"] | None = None
    unavailable_reason: str | None = None


class ProviderInput(StrictModel):
    operation: Literal["remove_background", "erase"]
    model: str
    image: bytes
    mask: bytes | None = None  # PNG, white = edit, black = preserve.
    prompt: str | None = None


class ImageProvider(Protocol):
    info: ProviderInfo

    async def edit(self, request: ProviderInput) -> bytes: ...


class ImageStore(Protocol):
    async def create_asset(
        self, owner: str, asset: ImageAsset, content: bytes
    ) -> None: ...
    async def get_asset(self, owner: str, asset_id: str) -> ImageAsset: ...
    async def get_content(self, owner: str, asset_id: str) -> bytes: ...
    async def list_assets(self, owner: str, limit: int) -> list[ImageAsset]: ...
    async def add_comment(self, owner: str, comment: ImageComment) -> None: ...
    async def list_comments(self, owner: str, asset_id: str) -> list[ImageComment]: ...
    async def delete_comment(
        self, owner: str, asset_id: str, comment_id: str
    ) -> None: ...
