from .config import settings
from .log import setup_logging
from .storage import parse_data_url_to_bytes

__all__ = ["parse_data_url_to_bytes", "settings", "setup_logging", "upload_image"]


def __getattr__(name: str) -> object:
    if name == "upload_image":
        from api.utils.object_storage.aliyun_oss import upload_image

        return upload_image
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
