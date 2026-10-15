import base64
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import quote

from .config import settings


def parse_data_url_to_bytes(data_url: str) -> bytes:
    """Decode a base64 data URL into bytes."""
    if not data_url.startswith("data:") or "base64," not in data_url:
        raise ValueError("Expected a base64 data URL")

    _, encoded = data_url.split("base64,", maxsplit=1)
    return base64.b64decode(encoded)


def upload_image(
    filename: str,
    data: str | bytes,
    prefix: str = "tmp",
    rename: bool = True,
    domain: str | None = None,
) -> str:
    """Persist image bytes under the API data directory and return a public URL."""
    suffix = Path(filename).suffix
    safe_name = Path(filename).name
    upload_name = f"{uuid.uuid4()}{suffix}" if rename else safe_name
    object_path = Path(prefix or "tmp") / upload_name
    target = settings.data_dir / object_path
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = data.encode() if isinstance(data, str) else data
    target.write_bytes(payload)
    mimetypes.add_type("image/webp", ".webp")

    public_path = quote(object_path.as_posix())
    if domain:
        return f"https://{domain.rstrip('/')}/{public_path}"
    return f"/api/files/{public_path}"
