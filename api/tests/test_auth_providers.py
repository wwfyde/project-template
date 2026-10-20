import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pytest import MonkeyPatch

from api.core.auth_config import DingTalkAuthConfig, GoogleAuthConfig
from api.services.auth_providers import AuthProviderError
from api.services.auth_providers.dingtalk import DingTalkProvider
from api.services.auth_providers.google import GoogleProvider, JWKS_URL, TOKEN_URL

CLIENT_ID = "test-client.apps.googleusercontent.com"
NONCE = "test-browser-bound-nonce"
VERIFIER = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJK"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_config() -> GoogleAuthConfig:
    return GoogleAuthConfig.model_validate(
        {"client_id": CLIENT_ID, "client_secret": "test-client-secret"}
    )


def valid_claims() -> dict[str, object]:
    now = int(time.time())
    return {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "iat": now - 1,
        "exp": now + 300,
        "sub": "google-subject-123",
        "nonce": NONCE,
        "name": "Test User",
        "email": "user@example.com",
        "email_verified": True,
        "picture": "https://example.com/avatar.png",
    }


def mock_google(
    monkeypatch: MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    token: str,
    *,
    token_status: int = 200,
    malformed_keys: bool = False,
) -> list[httpx2.Request]:
    requests: list[httpx2.Request] = []
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    key.update({"kid": "google-key", "alg": "RS256", "use": "sig"})

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            assert parse_qs(request.content.decode())["code_verifier"] == [VERIFIER]
            return httpx2.Response(token_status, json={"id_token": token})
        assert str(request.url) == JWKS_URL
        return httpx2.Response(200, json={} if malformed_keys else {"keys": [key]})

    client_type = httpx2.AsyncClient
    monkeypatch.setattr(
        httpx2,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx2.MockTransport(handler), **kwargs),
    )
    return requests


def sign(claims: dict[str, object], key: rsa.RSAPrivateKey) -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "google-key"})


def test_google_authorization_uses_state_nonce_and_s256_pkce() -> None:
    url = GoogleProvider(google_config()).build_authorize_url(
        state="browser-state", nonce=NONCE, code_verifier=VERIFIER
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["state"] == ["browser-state"]
    assert query["nonce"] == [NONCE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] != [VERIFIER]
    assert "client_secret" not in query
    assert "code_verifier" not in query


def test_account_operations_request_interactive_google_account_selection() -> None:
    provider = GoogleProvider(google_config())
    ordinary = parse_qs(
        urlsplit(
            provider.build_authorize_url(
                state="state", nonce=NONCE, code_verifier=VERIFIER
            )
        ).query
    )
    account = parse_qs(
        urlsplit(
            provider.build_authorize_url(
                state="state", nonce=NONCE, code_verifier=VERIFIER, interactive=True
            )
        ).query
    )
    assert "prompt" not in ordinary
    assert set(account["prompt"][0].split()) == {"select_account", "consent"}
    assert account["code_challenge"] == ordinary["code_challenge"]
    assert "max_age" not in account


@pytest.mark.asyncio
async def test_google_verifies_signed_identity_and_uses_subject(
    monkeypatch: MonkeyPatch, signing_key: rsa.RSAPrivateKey
) -> None:
    requests = mock_google(monkeypatch, signing_key, sign(valid_claims(), signing_key))
    identity = await GoogleProvider(google_config()).authenticate(
        "authorization-code", nonce=NONCE, code_verifier=VERIFIER
    )
    assert identity.provider == "google"
    assert identity.subject == "google-subject-123"
    assert identity.email == "user@example.com"
    assert [str(request.url) for request in requests] == [TOKEN_URL, JWKS_URL]


@pytest.mark.parametrize(
    "mutation",
    [
        {"iss": "https://attacker.example"},
        {"aud": "another-client"},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"iat": "1"},
        {"sub": ""},
        {"sub": 42},
        {"nonce": "another-browser"},
        {"nonce": None},
        {"azp": "another-client"},
        {"aud": [CLIENT_ID, "another-client"]},
        {"name": {"unexpected": "object"}},
        {"picture": "javascript:alert(1)"},
    ],
)
@pytest.mark.asyncio
async def test_google_rejects_invalid_token_claims(
    monkeypatch: MonkeyPatch,
    signing_key: rsa.RSAPrivateKey,
    mutation: dict[str, object],
) -> None:
    claims = valid_claims() | mutation
    mock_google(monkeypatch, signing_key, sign(claims, signing_key))
    with pytest.raises(AuthProviderError):
        await GoogleProvider(google_config()).authenticate(
            "authorization-code", nonce=NONCE, code_verifier=VERIFIER
        )


@pytest.mark.asyncio
async def test_google_rejects_missing_nonce_and_invalid_signature(
    monkeypatch: MonkeyPatch, signing_key: rsa.RSAPrivateKey
) -> None:
    for mutate in (True, False):
        claims = valid_claims()
        if mutate:
            claims.pop("nonce")
            key = signing_key
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with monkeypatch.context() as patch:
            mock_google(patch, signing_key, sign(claims, key))
            with pytest.raises(AuthProviderError):
                await GoogleProvider(google_config()).authenticate(
                    "code", nonce=NONCE, code_verifier=VERIFIER
                )


@pytest.mark.parametrize("failure", ["algorithm", "jwks", "token_endpoint"])
@pytest.mark.asyncio
async def test_google_rejects_upstream_or_key_failures(
    monkeypatch: MonkeyPatch, signing_key: rsa.RSAPrivateKey, failure: str
) -> None:
    token = (
        jwt.encode(
            valid_claims(),
            "a-long-enough-test-secret-for-hs256",
            algorithm="HS256",
            headers={"kid": "google-key"},
        )
        if failure == "algorithm"
        else sign(valid_claims(), signing_key)
    )
    mock_google(
        monkeypatch,
        signing_key,
        token,
        token_status=400 if failure == "token_endpoint" else 200,
        malformed_keys=failure == "jwks",
    )
    with pytest.raises(AuthProviderError) as error:
        await GoogleProvider(google_config()).authenticate(
            "private-code", nonce=NONCE, code_verifier=VERIFIER
        )
    assert token not in str(error.value)
    assert "private-code" not in str(error.value)


@pytest.mark.asyncio
async def test_google_does_not_retain_unverified_email(
    monkeypatch: MonkeyPatch, signing_key: rsa.RSAPrivateKey
) -> None:
    claims = valid_claims() | {"email_verified": False}
    mock_google(monkeypatch, signing_key, sign(claims, signing_key))
    identity = await GoogleProvider(google_config()).authenticate(
        "code", nonce=NONCE, code_verifier=VERIFIER
    )
    assert identity.email is None


@pytest.mark.parametrize(
    "profile",
    [
        {"unionId": "union-123", "nick": "Test User"},
        {"unionId": 123, "nick": "Test User"},
    ],
)
@pytest.mark.asyncio
async def test_dingtalk_translates_only_valid_provider_identity(
    monkeypatch: MonkeyPatch, profile: dict[str, object]
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            return httpx2.Response(200, json={"accessToken": "upstream-token"})
        assert request.headers["x-acs-dingtalk-access-token"] == "upstream-token"
        return httpx2.Response(200, json=profile)

    client_type = httpx2.AsyncClient
    monkeypatch.setattr(
        httpx2,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx2.MockTransport(handler), **kwargs),
    )
    provider = DingTalkProvider(DingTalkAuthConfig())
    if isinstance(profile["unionId"], str):
        identity = await provider.authenticate(
            "code", nonce=NONCE, code_verifier=VERIFIER
        )
        assert identity.subject == "union-123"
        assert identity.provider == "dingtalk"
    else:
        with pytest.raises(AuthProviderError):
            await provider.authenticate("code", nonce=NONCE, code_verifier=VERIFIER)
