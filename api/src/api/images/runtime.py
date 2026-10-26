from api.core.config import Settings
from api.images.contracts import ImageFailure, ImageStore
from api.images.service import ImageService
from api.images.store import InMemoryImageStore, PostgresImageStore


def create_image_service(settings: Settings) -> ImageService:
    from api.images.providers import build_providers

    store: ImageStore
    if settings.repo_type == "in-memory":
        store = InMemoryImageStore()
    elif settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        store = PostgresImageStore(AsyncSessionLocal)
    else:
        raise ImageFailure(
            "unsupported_store", "Images support in-memory or postgres storage.", 503
        )
    return ImageService(
        store=store, providers=build_providers(settings), config=settings.images
    )
