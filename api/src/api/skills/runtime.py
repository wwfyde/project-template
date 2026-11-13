"""Composition and durable object-deletion retries for application-owned skills."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from api.core.config import Settings
from api.skills.contracts import SkillFailure
from api.skills.service import SkillService

logger = logging.getLogger(__name__)


def create_skill_service(settings: Settings) -> SkillService:
    if settings.oss is None:
        raise SkillFailure(
            "skill_storage_unconfigured", "Skills require object storage configuration.", 503
        )
    from api.core.db import AsyncSessionLocal
    from api.skills.objects import AliyunSkillObjectStorage
    from api.skills.store import PostgresSkillStore

    # Skills always persist to the database, regardless of example repository mode.
    return SkillService(
        PostgresSkillStore(AsyncSessionLocal), AliyunSkillObjectStorage(settings.oss)
    )


async def _cleanup_worker(service: SkillService) -> None:
    while True:
        try:
            await service.cleanup()
        except Exception:
            logger.warning("Skill cleanup storage is unavailable; retrying later")
        await asyncio.sleep(30)


@asynccontextmanager
async def skill_lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
    if settings.oss is None:
        yield
        return
    service = getattr(app.state, "skill_service", None)
    if service is None:
        service = create_skill_service(settings)
        app.state.skill_service = service
    worker = asyncio.create_task(_cleanup_worker(service), name="skill-object-cleanup")
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
