from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from api.core.header_auth import HeaderAuthConfig


class OAuthProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    redirect_uri: str
    scope: str = "openid"
    timeout_seconds: float = Field(default=10, gt=0, le=120)

    @field_validator("redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or "\\" in value
            or any(ord(char) < 33 for char in value)
        ):
            raise ValueError("redirect_uri must be an absolute HTTP(S) callback URL")
        return value

    @property
    def ready(self) -> bool:
        return bool(
            self.enabled
            and self.client_id.strip()
            and self.client_secret.get_secret_value().strip()
        )


class GoogleAuthConfig(OAuthProviderConfig):
    enabled: bool = True
    redirect_uri: str = "http://localhost:8000/api/auth/oauth/google/callback"
    scope: str = "openid email profile"

    @field_validator("scope")
    @classmethod
    def require_openid_scope(cls, value: str) -> str:
        if "openid" not in value.split():
            raise ValueError("Google authentication requires the openid scope")
        return value


class DingTalkAuthConfig(OAuthProviderConfig):
    enabled: bool = True
    redirect_uri: str = "http://localhost:8000/api/auth/oauth/dingtalk/callback"


class PhoneAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False

    @field_validator("enabled")
    @classmethod
    def reject_unimplemented_channel(cls, value: bool) -> bool:
        if value:
            raise ValueError("Phone authentication is reserved and not implemented")
        return value


class PasswordAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    rate_limit_attempts: int = Field(default=10, ge=1, le=1000)
    ip_rate_limit_attempts: int = Field(default=50, ge=1, le=10000)
    rate_limit_window_seconds: int = Field(default=300, ge=1, le=3600)


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    providers: list[str] = Field(
        default_factory=lambda: ["google", "password", "dingtalk", "phone"]
    )
    default_tenant_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        deprecated=True,
        description="Accepted for old configs; new users receive a personal account.",
    )
    allow_signup: bool = True
    session_key_prefix: str = Field(
        default="project-template:auth", min_length=1, max_length=128
    )
    frontend_url: str = "http://localhost:5173"
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    reauth_max_age_seconds: int = Field(default=300, ge=60, le=1800)
    google: GoogleAuthConfig = Field(default_factory=GoogleAuthConfig)
    dingtalk: DingTalkAuthConfig = Field(default_factory=DingTalkAuthConfig)
    phone: PhoneAuthConfig = Field(default_factory=PhoneAuthConfig)
    password: PasswordAuthConfig = Field(default_factory=PasswordAuthConfig)
    header: HeaderAuthConfig = Field(default_factory=HeaderAuthConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_dingtalk_config(cls, value: object) -> object:
        """Accept the original fs-agent DingTalk configuration at the boundary.

        Redis SDK sessions do not use the former signed-state session_secret.
        A shared frontend_url explicitly supplied by the caller takes priority.
        """
        if not isinstance(value, dict) or not isinstance(value.get("dingtalk"), dict):
            return value
        result = dict(value)
        dingtalk = dict(result["dingtalk"])
        frontend_url = dingtalk.pop("frontend_url", None)
        dingtalk.pop("session_secret", None)
        if "frontend_url" not in result and frontend_url is not None:
            result["frontend_url"] = frontend_url
        result["dingtalk"] = dingtalk
        return result

    @field_validator("session_key_prefix")
    @classmethod
    def validate_session_key_prefix(cls, value: str) -> str:
        if not value.strip() or any(
            ord(char) < 33 or ord(char) == 127 for char in value
        ):
            raise ValueError(
                "session_key_prefix cannot contain whitespace or control characters"
            )
        return value

    @field_validator("providers")
    @classmethod
    def validate_providers(cls, value: list[str]) -> list[str]:
        if "google" not in value:
            raise ValueError("auth.providers must include google")
        if len(value) != len(set(value)):
            raise ValueError("auth.providers must not contain duplicate providers")
        return value

    @field_validator("frontend_url")
    @classmethod
    def validate_frontend_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(ord(char) < 33 for char in value)
        ):
            raise ValueError("frontend_url must be an HTTP(S) origin without a path")
        return value.rstrip("/")
