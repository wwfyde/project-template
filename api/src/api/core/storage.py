import base64


def parse_data_url_to_bytes(data_url: str) -> bytes:
    """Decode a base64 data URL into bytes."""
    if not data_url.startswith("data:") or "base64," not in data_url:
        raise ValueError("Expected a base64 data URL")
    _, encoded = data_url.split("base64,", maxsplit=1)
    return base64.b64decode(encoded)


def __getattr__(name: str) -> object:
    if name == "upload_image":
        from api.utils.object_storage.aliyun_oss import upload_image

        return upload_image
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
