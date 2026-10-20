import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import urlencode

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import ValidationError

from api.core.auth_config import GoogleAuthConfig
from api.services.auth_providers.base import AuthProviderError
from api.schemas.auth import ProviderIdentity

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class GoogleProvider:
    def __init__(self, config: GoogleAuthConfig) -> None:
        self._config = config

    def build_authorize_url(
        self, *, state: str, nonce: str, code_verifier: str, interactive: bool = False
    ) -> str:
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        parameters = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": self._config.scope,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if interactive:
            parameters["prompt"] = "select_account consent"
        query = urlencode(parameters)
        return f"{AUTHORIZE_URL}?{query}"

    async def authenticate(
        self, code: str, *, nonce: str, code_verifier: str
    ) -> ProviderIdentity:
        try:
            async with httpx2.AsyncClient(
                timeout=self._config.timeout_seconds, follow_redirects=False
            ) as client:
                response = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._config.client_id,
                        "client_secret": self._config.client_secret.get_secret_value(),
                        "redirect_uri": self._config.redirect_uri,
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": code_verifier,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("id_token"), str
                ):
                    raise AuthProviderError("Google returned no identity token")
                token = payload["id_token"]
                header = jwt.get_unverified_header(token)
                if header.get("alg") != "RS256" or not isinstance(
                    header.get("kid"), str
                ):
                    raise AuthProviderError(
                        "Google identity token has an invalid signing key"
                    )

                keys_response = await client.get(JWKS_URL)
                keys_response.raise_for_status()
                signing_key = self._select_signing_key(
                    keys_response.json(), header["kid"]
                )

            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self._config.client_id,
                issuer=ISSUERS,
                options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce"]},
            )
            return self._identity_from_claims(claims, nonce=nonce)
        except AuthProviderError:
            raise
        except (
            httpx2.HTTPError,
            jwt.PyJWTError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            raise AuthProviderError("Google authentication failed") from exc

    @staticmethod
    def _select_signing_key(payload: object, kid: str) -> RSAPublicKey:
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise AuthProviderError("Google signing keys are unavailable")
        keys = [
            key
            for key in payload["keys"]
            if isinstance(key, dict)
            and key.get("kid") == kid
            and key.get("kty") == "RSA"
            and key.get("alg", "RS256") == "RS256"
            and key.get("use", "sig") == "sig"
            and ("key_ops" not in key or "verify" in key["key_ops"])
        ]
        if len(keys) != 1:
            raise AuthProviderError("Google identity token has an unknown signing key")
        key = jwt.PyJWK.from_dict(keys[0], algorithm="RS256").key
        if not isinstance(key, RSAPublicKey):
            raise AuthProviderError("Google identity token has an invalid signing key")
        return key

    def _identity_from_claims(
        self, claims: dict[str, Any], *, nonce: str
    ) -> ProviderIdentity:
        actual_nonce = claims.get("nonce")
        if (
            not nonce
            or not isinstance(actual_nonce, str)
            or not hmac.compare_digest(actual_nonce.encode(), nonce.encode())
        ):
            raise AuthProviderError("Google identity token nonce mismatch")
        if (
            type(claims.get("exp")) is not int
            or type(claims.get("iat")) is not int
            or claims["exp"] <= claims["iat"]
        ):
            raise AuthProviderError("Google identity token has invalid timestamps")
        audience = claims.get("aud")
        authorized_party = claims.get("azp")
        if (
            authorized_party is not None and authorized_party != self._config.client_id
        ) or (
            isinstance(audience, list)
            and len(audience) > 1
            and authorized_party is None
        ):
            raise AuthProviderError("Google identity token authorized party mismatch")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.isascii():
            raise AuthProviderError("Google identity token has an invalid subject")
        for field in ("name", "email", "picture"):
            if field in claims and not isinstance(claims[field], str):
                raise AuthProviderError("Google identity token has an invalid profile")
        email_verified = claims.get("email_verified")
        email = (
            claims.get("email")
            if email_verified is True or email_verified == "true"
            else None
        )
        try:
            return ProviderIdentity(
                provider="google",
                subject=subject,
                display_name=claims.get("name") or email or subject,
                avatar_url=claims.get("picture"),
                email=email,
            )
        except ValidationError as exc:
            raise AuthProviderError(
                "Google identity token has an invalid profile"
            ) from exc
