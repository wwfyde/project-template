from typing import Protocol

from api.auth.schemas import ProviderIdentity


class AuthProviderError(RuntimeError):
    """Safe authentication error; never includes upstream bodies or credentials."""


class AuthProviderUnavailable(AuthProviderError):
    pass


class OAuthProvider(Protocol):
    def build_authorize_url(
        self, *, state: str, nonce: str, code_verifier: str
    ) -> str: ...

    async def authenticate(
        self, code: str, *, nonce: str, code_verifier: str
    ) -> ProviderIdentity: ...
