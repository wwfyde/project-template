"""Production composition and lifecycle retries without live infrastructure."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from api.core.config import AliyunOssConfig, settings
from api.skills import runtime
from api.skills.contracts import SkillFailure
from api.skills.objects import AliyunSkillObjectStorage
from api.skills.store import PostgresSkillStore
from fastapi import FastAPI
from pytest import MonkeyPatch


def test_skills_persist_even_when_example_repository_mode_is_memory() -> None:
    configured = settings.model_copy(
        update={
            "repo_type": "memory",
            "oss": AliyunOssConfig(
                bucket_name="private-skills",
                region="cn-hangzhou",
                access_key_id="test",
                access_key_secret="test",
            ),
        }
    )
    service = runtime.create_skill_service(configured)
    assert isinstance(service.store, PostgresSkillStore)
    assert isinstance(service.objects, AliyunSkillObjectStorage)


@pytest.mark.asyncio
async def test_missing_oss_disables_only_skills_and_starts_no_worker() -> None:
    configured = settings.model_copy(update={"oss": None})
    with pytest.raises(SkillFailure) as failure:
        runtime.create_skill_service(configured)
    assert failure.value.status == 503
    app = FastAPI()
    async with runtime.skill_lifespan(app, configured):
        assert not hasattr(app.state, "skill_service")


@pytest.mark.asyncio
async def test_cleanup_worker_recovers_from_outage_and_stops_with_lifespan(
    monkeypatch: MonkeyPatch,
) -> None:
    configured = settings.model_copy(
        update={
            "oss": AliyunOssConfig(
                bucket_name="private-skills",
                access_key_id="test",
                access_key_secret="test",
            ),
        }
    )
    service = MagicMock()
    service.cleanup = AsyncMock(side_effect=[RuntimeError("database unavailable"), None])
    app = FastAPI()
    app.state.skill_service = service
    retried = asyncio.Event()
    hold = asyncio.Event()
    sleeps = 0

    async def controlled_sleep(seconds: int) -> None:
        nonlocal sleeps
        assert seconds == 30
        sleeps += 1
        if sleeps == 2:
            retried.set()
            await hold.wait()

    monkeypatch.setattr(runtime.asyncio, "sleep", controlled_sleep)
    async with runtime.skill_lifespan(app, configured):
        await asyncio.wait_for(retried.wait(), timeout=1)
        worker = next(
            task for task in asyncio.all_tasks() if task.get_name() == "skill-object-cleanup"
        )
        assert service.cleanup.await_count == 2
        assert not worker.done()
    assert worker.done()
