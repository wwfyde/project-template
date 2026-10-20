from urllib.parse import urlencode

import httpx2

from api.core.auth_config import DingTalkAuthConfig
from api.services.auth_providers.base import AuthProviderError
from api.schemas.auth import ProviderIdentity

AUTHORIZE_URL = "https://login.dingtalk.com/oauth2/auth"
TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
ME_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


class DingTalkProvider:
    def __init__(self, config: DingTalkAuthConfig) -> None:
        self._config = config

    def build_authorize_url(
        self, *, state: str, nonce: str, code_verifier: str, interactive: bool = False
    ) -> str:
        query = urlencode(
            {
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "client_id": self._config.client_id,
                "scope": self._config.scope,
                "state": state,
                "prompt": "consent",
            }
        )
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
                    json={
                        "clientId": self._config.client_id,
                        "clientSecret": self._config.client_secret.get_secret_value(),
                        "code": code,
                        "grantType": "authorization_code",
                    },
                )
                response.raise_for_status()
                token_payload = response.json()
                token = (
                    token_payload.get("accessToken")
                    if isinstance(token_payload, dict)
                    else None
                )
                if not isinstance(token, str) or not token:
                    raise AuthProviderError("DingTalk returned no access token")
                response = await client.get(
                    ME_URL, headers={"x-acs-dingtalk-access-token": token}
                )
                response.raise_for_status()
                profile = response.json()
                if not isinstance(profile, dict):
                    raise AuthProviderError("DingTalk returned an invalid profile")
                return ProviderIdentity(
                    provider="dingtalk",
                    subject=profile.get("unionId"),
                    display_name=profile.get("nick"),
                    avatar_url=profile.get("avatarUrl"),
                )
        except AuthProviderError:
            raise
        except (httpx2.HTTPError, ValueError, TypeError) as exc:
            raise AuthProviderError("DingTalk authentication failed") from exc
