from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from api.auth.config import AuthConfig
from api.auth.providers.base import (
    AuthProviderError,
    AuthProviderUnavailable,
    OAuthProvider,
)
from api.auth.providers.dingtalk import DingTalkProvider
from api.auth.providers.google import GoogleProvider
from api.auth.schemas import AuthProviderSummary, ProviderIdentity


@dataclass(frozen=True)
class ProviderRegistration:
    method: Literal["oauth", "otp", "password"]
    factory: Callable[[AuthConfig], OAuthProvider] | None
    ready: Callable[[AuthConfig], bool]
    implemented: bool = True


# A new identity source plugs into this registry; routes remain provider-independent.
PROVIDER_REGISTRY: dict[str, ProviderRegistration] = {
    "google": ProviderRegistration(
        "oauth",
        lambda config: GoogleProvider(config.google),
        lambda config: config.google.ready,
    ),
    "dingtalk": ProviderRegistration(
        "oauth",
        lambda config: DingTalkProvider(config.dingtalk),
        lambda config: config.dingtalk.ready,
    ),
    "password": ProviderRegistration(
        "password", None, lambda config: config.password.enabled
    ),
    "phone": ProviderRegistration("otp", None, lambda config: False, implemented=False),
}


def validate_provider_configuration(config: AuthConfig) -> None:
    unknown = set(config.providers) - PROVIDER_REGISTRY.keys()
    if unknown:
        raise ValueError(
            f"Unknown authentication providers: {', '.join(sorted(unknown))}"
        )


def get_auth_providers(config: AuthConfig) -> list[AuthProviderSummary]:
    validate_provider_configuration(config)
    return [
        AuthProviderSummary(
            id=provider_id,
            method=registration.method,
            enabled=registration.implemented and registration.ready(config),
            implemented=registration.implemented,
            start_path=f"/api/auth/oauth/{provider_id}/start"
            if registration.method == "oauth"
            else None,
        )
        for provider_id in config.providers
        for registration in [PROVIDER_REGISTRY[provider_id]]
    ]


def get_oauth_provider(provider_id: str, config: AuthConfig) -> OAuthProvider:
    registration = PROVIDER_REGISTRY.get(provider_id)
    if (
        provider_id not in config.providers
        or registration is None
        or registration.method != "oauth"
        or registration.factory is None
        or not registration.ready(config)
    ):
        raise AuthProviderUnavailable("Authentication provider is not available")
    return registration.factory(config)


__all__ = [
    "AuthProviderError",
    "AuthProviderUnavailable",
    "OAuthProvider",
    "ProviderIdentity",
    "get_auth_providers",
    "get_oauth_provider",
    "validate_provider_configuration",
]
