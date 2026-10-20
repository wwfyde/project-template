from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    computed_field,
    field_validator,
)


class ProviderIdentity(BaseModel):
    """Verified provider identity, resolved to an application user before login."""

    model_config = ConfigDict(strict=True)

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("subject", "display_name", "email", "phone")
    @classmethod
    def validate_profile_text(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError(
                "Identity fields cannot be blank or contain control characters"
            )
        return value

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or "\\" in value
            or any(ord(char) < 33 for char in value)
        ):
            raise ValueError("Avatar must be an HTTP(S) URL")
        return value


class AuthUser(BaseModel):
    id: str
    provider: str
    display_name: str
    avatar_url: str | None = None
    email: str | None = None
    phone: str | None = None
    account_id: str

    @computed_field
    @property
    def tenant_id(self) -> str:
        """Compatibility output for clients using the former tenant field."""
        return self.account_id


class AuthProviderSummary(BaseModel):
    id: str
    method: Literal["oauth", "otp", "password"]
    enabled: bool
    implemented: bool = True
    start_path: str | None = None


class AuthSessionResponse(BaseModel):
    authenticated: bool
    user: AuthUser | None = None
    providers: list[AuthProviderSummary] = Field(default_factory=list)
    csrf_token: str | None = None


class PasswordLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)


class OAuthAttempt(BaseModel):
    provider: str
    browser_digest: str
    nonce: str
    code_verifier: str
    return_to: str
    intent: Literal["login", "link", "reauth"] = "login"
    user_id: str | None = None
    account_id: str | None = None
    auth_version: int | None = None
    session_digest: str | None = None
    current_provider: str | None = None
