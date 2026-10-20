import unicodedata
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from api.schemas.auth import AuthProviderSummary, AuthUser, ProviderIdentity


class AccountIdentity(BaseModel):
    id: str
    provider: str
    username: str | None = None
    enabled: bool
    current: bool
    can_unlink: bool


class ReauthenticationStatus(BaseModel):
    required: bool
    expires_in: int


class AccountSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None = None
    structure: Literal["personal", "workspace"] = "personal"


class AccountRead(BaseModel):
    account: AccountSummary
    user: AuthUser
    identities: list[AccountIdentity]
    providers: list[AuthProviderSummary]
    reauthentication: ReauthenticationStatus


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str:
        if (
            value is None
            or not value.strip()
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)
        ):
            raise ValueError(
                "Display name must be nonempty text without control characters"
            )
        return value.strip()

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar(cls, value: str | None) -> str | None:
        return ProviderIdentity.validate_avatar_url(value)

    @model_validator(mode="after")
    def require_change(self) -> "ProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide a display name or avatar URL")
        return self


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: SecretStr = Field(min_length=12, max_length=1024)
    current_password: SecretStr | None = Field(
        default=None, min_length=1, max_length=1024
    )


class PasswordReauthentication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=1024)


class AccountMutationResponse(BaseModel):
    requires_login: bool = False


class AuthorizationStart(BaseModel):
    authorization_url: str
