import pytest
from pydantic import ValidationError

from api.core.auth_config import AuthConfig
from api.services.auth_providers import (
    AuthProviderUnavailable,
    get_auth_providers,
    get_oauth_provider,
    validate_provider_configuration,
)
from api.core.oauth import sanitize_return_to


def test_provider_catalog_is_configured_and_phone_is_reserved() -> None:
    config = AuthConfig()
    providers = get_auth_providers(config)
    assert [provider.id for provider in providers] == [
        "google",
        "password",
        "dingtalk",
        "phone",
    ]
    assert not any(provider.enabled for provider in providers)
    assert providers[0].implemented
    assert providers[1].implemented
    assert providers[1].method == "password"
    assert providers[1].start_path is None
    assert not providers[3].implemented
    assert providers[3].start_path is None


def test_oauth_defaults_enable_configured_credentials_only() -> None:
    config = AuthConfig.model_validate(
        {
            "google": {"client_id": "google-client", "client_secret": "test-secret"},
            "dingtalk": {
                "client_id": "dingtalk-client",
                "client_secret": "test-secret",
            },
        }
    )
    availability = {
        provider.id: provider.enabled for provider in get_auth_providers(config)
    }
    assert availability["google"] and availability["dingtalk"]
    config.dingtalk.enabled = False
    assert not get_auth_providers(config)[2].enabled


def test_original_dingtalk_config_remains_usable_without_retaining_unused_secret() -> (
    None
):
    source = {
        "dingtalk": {
            "client_id": "test-client",
            "client_secret": "test-secret",
            "frontend_url": "http://localhost:6173",
            "redirect_uri": "http://localhost:9036/api/auth/dingtalk/callback",
            "session_secret": "obsolete-secret-never-retained",
        }
    }
    config = AuthConfig.model_validate(source)
    assert config.frontend_url == "http://localhost:6173"
    assert config.dingtalk.ready
    assert config.dingtalk.redirect_uri.endswith("/api/auth/dingtalk/callback")
    assert "obsolete-secret-never-retained" not in config.model_dump_json()
    assert source["dingtalk"]["session_secret"] == "obsolete-secret-never-retained"
    assert (
        AuthConfig.model_validate(
            {**source, "frontend_url": "https://app.example.test"}
        ).frontend_url
        == "https://app.example.test"
    )


def test_provider_order_and_credentials_control_available_login_sources() -> None:
    config = AuthConfig.model_validate(
        {
            "providers": ["dingtalk", "google"],
            "google": {"client_id": "client-id", "client_secret": "secret"},
        }
    )
    providers = get_auth_providers(config)
    assert [provider.id for provider in providers] == ["dingtalk", "google"]
    assert not providers[0].enabled
    assert providers[1].enabled
    assert providers[1].start_path == "/api/auth/oauth/google/start"
    assert get_oauth_provider("google", config) is not None
    with pytest.raises(AuthProviderUnavailable):
        get_oauth_provider("dingtalk", config)


@pytest.mark.parametrize(
    "config",
    [
        {"providers": []},
        {"providers": ["dingtalk"]},
        {"providers": ["google", "google"]},
        {"phone": {"enabled": True}},
        {"frontend_url": "https://example.com/login"},
        {"frontend_url": "https://username:password@example.com"},
        {"frontend_url": "javascript:alert(1)"},
        {"google": {"redirect_uri": "//example.com/callback"}},
        {"google": {"scope": "email profile"}},
        {"default_tenant_id": "tenant\nforged"},
        {"session_key_prefix": "auth\nforged"},
    ],
)
def test_invalid_auth_configuration_fails_closed(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AuthConfig.model_validate(config)


def test_unknown_and_unimplemented_provider_cannot_be_started() -> None:
    config = AuthConfig(providers=["google", "unknown"])
    with pytest.raises(ValueError, match="Unknown authentication providers"):
        validate_provider_configuration(config)
    for provider_id in ("unknown", "phone", "google"):
        with pytest.raises(AuthProviderUnavailable):
            get_oauth_provider(provider_id, AuthConfig())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "/"),
        ("/assets?view=grid#recent", "/assets?view=grid#recent"),
        ("/hello%20world", "/hello%20world"),
        ("https://attacker.example", "/"),
        ("//attacker.example", "/"),
        ("/\\attacker.example", "/"),
        ("/%2fattacker.example", "/"),
        ("/%252fattacker.example", "/"),
        ("/%5cattacker.example", "/"),
        ("/%0d%0aLocation:evil", "/"),
        ("/\t/attacker.example", "/"),
        ("assets", "/"),
    ],
)
def test_return_path_cannot_escape_application_origin(
    value: str | None, expected: str
) -> None:
    assert sanitize_return_to(value) == expected
