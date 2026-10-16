"""Configuration and principal for opt-in service-to-service authentication."""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

HEADER_EXAMPLE_PREFIX = "/api/examples/auth-header"

_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_RESERVED_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "host",
    "connection",
    "content-type",
    "content-length",
    "transfer-encoding",
    "keep-alive",
    "upgrade",
    "cache-control",
    "vary",
    "location",
    "www-authenticate",
    "origin",
    "referer",
    "request-id",
    "user-id",
    "tenant-id",
    "x-request-id",
    "x-user-id",
    "x-tenant-id",
    "x-csrf-token",
    "traceparent",
    "tracestate",
    "baggage",
}


class HeaderAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = False
    name: str = Field(default="X-Api-Key", min_length=1, max_length=64)
    keys: list[SecretStr] = Field(default_factory=list, max_length=16)

    @field_validator("name")
    @classmethod
    def validate_header_name(cls, value: str) -> str:
        if not _HEADER_NAME.fullmatch(value) or value.lower() in _RESERVED_HEADERS:
            raise ValueError("API keys require a valid, dedicated HTTP header name")
        return value

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, value: list[SecretStr]) -> list[SecretStr]:
        for key in value:
            secret = key.get_secret_value()
            if not 32 <= len(secret) <= 512 or any(
                not 33 <= ord(char) <= 126 for char in secret
            ):
                raise ValueError(
                    "API keys must contain 32 to 512 visible ASCII characters"
                )
        return value


@dataclass(frozen=True, slots=True)
class HeaderPrincipal:
    """A service credential was verified; this is not an authenticated user."""

    scheme: Literal["api_key"] = "api_key"
