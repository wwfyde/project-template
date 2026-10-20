import hashlib
from urllib.parse import unquote, urlsplit

from fastapi.responses import RedirectResponse

from api.deps import SettingsDep


def sanitize_return_to(return_to: str | None) -> str:
    """Allow local paths only, including after nested percent decoding."""
    if not isinstance(return_to, str) or not return_to or len(return_to) > 2048:
        return "/"

    decoded = return_to
    for _ in range(5):
        if (
            not decoded.startswith("/")
            or decoded.startswith("//")
            or "\\" in decoded
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        ):
            return "/"
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            return "/"
        if parsed.scheme or parsed.netloc:
            return "/"
        expanded = unquote(decoded)
        if expanded == decoded:
            return return_to
        decoded = expanded
    return "/"


def _state_key(settings: SettingsDep, state: str) -> str:
    return f"{settings.auth.session_key_prefix}:{settings.app.env}:oauth:{hashlib.sha256(state.encode()).hexdigest()}"


def _redirect(settings: SettingsDep, path: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.auth.frontend_url}{sanitize_return_to(path)}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
