"""Coordinate database metadata and private object storage without provider calls."""

import logging
import time
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from api.skills.bundles import SkillBundle, validate_path
from api.skills.contracts import (
    DeletedSkill,
    DeletedSkillVersion,
    ObjectStorage,
    Skill,
    SkillFailure,
    SkillStore,
    SkillVersion,
)
from api.skills.preview import SkillFilePreview, SkillTree, build_tree, preview_file

logger = logging.getLogger(__name__)


class SkillService:
    def __init__(self, store: SkillStore, objects: ObjectStorage) -> None:
        self.store = store
        self.objects = objects

    async def cleanup(self) -> None:
        for key in await self.store.pending_deletes():
            try:
                await self.objects.delete(key)
                await self.store.acknowledge_delete(key)
            except Exception:
                # Leave the durable entry for the next worker iteration.
                await self.store.defer_delete(key)
                logger.warning("Skill object cleanup deferred")

    async def _compensate(self, key: str) -> None:
        try:
            # The store excludes referenced objects: a lost COMMIT acknowledgement
            # must never turn a successful upload into a dangling version.
            await self.store.queue_delete(key)
            await self.cleanup()
        except Exception:
            logger.error("Skill upload cleanup could not be queued; reconcile object storage")

    async def create(self, owner: str, bundle: SkillBundle) -> Skill:
        skill_id, version_id = f"skill_{uuid4().hex}", f"skillver_{uuid4().hex}"
        key = f"skills/{skill_id}/{version_id}.zip"
        try:
            await self.objects.put(key, bundle.archive)
            return await self.store.create(
                owner,
                skill_id,
                version_id,
                int(time.time()),
                bundle.name,
                bundle.description,
                key,
                bundle.files,
            )
        except BaseException:
            await self._compensate(key)
            raise

    async def create_version(
        self,
        owner: str,
        skill_id: str,
        bundle: SkillBundle,
        make_default: bool = False,
    ) -> SkillVersion:
        # Check ownership before uploading, and again under the database write lock.
        await self.store.get_skill(owner, skill_id)
        version_id = f"skillver_{uuid4().hex}"
        key = f"skills/{skill_id}/{version_id}.zip"
        try:
            await self.objects.put(key, bundle.archive)
            return await self.store.create_version(
                owner,
                skill_id,
                version_id,
                int(time.time()),
                bundle.name,
                bundle.description,
                key,
                bundle.files,
                make_default,
            )
        except BaseException:
            await self._compensate(key)
            raise

    async def delete_skill(self, owner: str, skill_id: str) -> DeletedSkill:
        deleted = await self.store.delete_skill(owner, skill_id)
        # The lifespan worker performs remote deletion; metadata revocation is immediate.
        return deleted

    async def delete_version(self, owner: str, skill_id: str, version: str) -> DeletedSkillVersion:
        return await self.store.delete_version(owner, skill_id, version)

    async def content(
        self,
        owner: str,
        skill_id: str,
        version: str | None = None,
    ) -> tuple[bytes, SkillVersion]:
        stored = await self.store.get_version(owner, skill_id, version)
        return await self.objects.get(stored.archive_key), stored.version

    async def tree(self, owner: str, skill_id: str, version: str | None = None) -> SkillTree:
        return build_tree(await self.store.get_version(owner, skill_id, version))

    async def file(
        self,
        owner: str,
        skill_id: str,
        path: str,
        version: str | None = None,
    ) -> SkillFilePreview:
        validate_path(path)
        stored = await self.store.get_version(owner, skill_id, version)
        if not any(file.path == path for file in stored.files):
            raise SkillFailure("skill_file_not_found", "Skill file not found.", 404)
        archive = await self.objects.get(stored.archive_key)
        return await run_in_threadpool(preview_file, stored, archive, path)
