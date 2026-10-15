"""Exercise the teaching routes without starting application services or using secrets."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import get_async_redis

from api.deps import get_db
from api.routes.examples import cache

IDENTIFIERS = [str(UUID(int=value)) for value in range(1, 5)]


def snapshot(identifier: str = IDENTIFIERS[0], title: str = "Redis lesson") -> dict:
    return {
        "id": identifier,
        "title": title,
        "is_archived": False,
        "updated_at": "2026-10-15T00:00:00Z",
    }


def query_result(row: dict | None) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    return result


def pipeline(results: list) -> MagicMock:
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock(return_value=results)
    return pipe


@pytest.fixture
def redis() -> MagicMock:
    return MagicMock(
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=True),
        delete=AsyncMock(return_value=1),
        eval=AsyncMock(),
    )


@pytest.fixture
def db() -> MagicMock:
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(
        execute=AsyncMock(return_value=query_result(snapshot())),
        begin=MagicMock(return_value=transaction),
    )


@pytest.fixture
def client(
    monkeypatch: MonkeyPatch, redis: MagicMock, db: MagicMock
) -> Iterator[TestClient]:
    monkeypatch.setattr(cache.settings.app, "env", "local")
    monkeypatch.setattr(cache.settings, "repo_type", "postgres")

    async def redis_override() -> MagicMock:
        return redis

    async def db_override() -> MagicMock:
        return db

    # Include only this router: application lifespan must never open real pools.
    app = FastAPI()
    app.include_router(cache.cache_router)
    app.dependency_overrides[get_async_redis] = redis_override
    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("as_bytes", [False, True])
def test_cache_hit_skips_database(
    client: TestClient, redis: MagicMock, db: MagicMock, as_bytes: bool
) -> None:
    raw = cache.ConversationSnapshot.model_validate(snapshot()).model_dump_json()
    redis.get.return_value = raw.encode() if as_bytes else raw

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["X-Cache"] == "HIT"
    db.execute.assert_not_awaited()
    redis.set.assert_not_awaited()


@pytest.mark.parametrize("raw", ["null", b"null"])
def test_negative_cache_hit_is_404_without_database_query(
    client: TestClient, redis: MagicMock, db: MagicMock, raw: str | bytes
) -> None:
    redis.get.return_value = raw

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    assert response.status_code == 404
    assert response.headers["X-Cache"] == "HIT"
    db.execute.assert_not_awaited()
    redis.set.assert_not_awaited()


def test_missing_record_gets_short_negative_cache(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    db.execute.return_value = query_result(None)

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    assert response.status_code == 404
    assert response.headers["X-Cache"] == "MISS"
    db.execute.assert_awaited_once()
    redis.set.assert_awaited_once()
    assert redis.set.await_args.args[1] == "null"
    assert 30 <= redis.set.await_args.kwargs["ex"] <= 35


def test_redis_read_and_write_failures_still_return_database_record(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    redis.get.side_effect = RedisConnectionError("offline")
    redis.set.side_effect = RedisConnectionError("offline")

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["X-Cache"] == "MISS"
    db.execute.assert_awaited_once()


@pytest.mark.parametrize("raw", ["invalid-json", '{"title":"old schema"}'])
def test_corrupt_cache_is_rebuilt_from_database(
    client: TestClient, redis: MagicMock, db: MagicMock, raw: str
) -> None:
    redis.get.return_value = raw

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["X-Cache"] == "MISS"
    db.execute.assert_awaited_once()
    redis.set.assert_awaited_once()
    assert 300 <= redis.set.await_args.kwargs["ex"] <= 360


def test_database_failure_does_not_poison_negative_cache(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    db.execute.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.get(f"/cache/conversations/{IDENTIFIERS[0]}")

    redis.set.assert_not_awaited()


@pytest.mark.parametrize("invalidation_fails", [False, True])
def test_update_invalidates_only_after_commit_and_preserves_committed_result(
    client: TestClient, redis: MagicMock, db: MagicMock, invalidation_fails: bool
) -> None:
    events = []

    async def commit(*args: object) -> bool:
        events.append("commit")
        return False

    async def invalidate(key: str) -> int:
        assert events == ["commit"]
        events.append("invalidate")
        if invalidation_fails:
            raise RedisConnectionError("offline")
        return 0  # An already absent key is also successful invalidation.

    db.begin.return_value.__aexit__.side_effect = commit
    db.execute.return_value = query_result(snapshot(title="Renamed"))
    redis.delete.side_effect = invalidate

    response = client.patch(
        f"/cache/conversations/{IDENTIFIERS[0]}", json={"title": "Renamed"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert events == ["commit", "invalidate"]
    assert (
        response.headers["X-Cache-Invalidated"] == str(not invalidation_fails).lower()
    )
    redis.delete.assert_awaited_once_with(cache._conversation_key(IDENTIFIERS[0]))


def test_failed_commit_keeps_existing_cache(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    db.begin.return_value.__aexit__.side_effect = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        client.patch(
            f"/cache/conversations/{IDENTIFIERS[0]}", json={"title": "Renamed"}
        )

    redis.delete.assert_not_awaited()


def test_batch_deduplicates_and_queries_only_misses_in_one_sql_statement(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    hit, negative, found, missing = IDENTIFIERS
    read_pipe = pipeline(
        [
            cache.ConversationSnapshot.model_validate(snapshot(hit)).model_dump_json(),
            b"null",
            None,
            None,
        ]
    )
    write_pipe = pipeline([True, True])
    redis.pipeline.side_effect = [read_pipe, write_pipe]
    db.execute.return_value.mappings.return_value = [snapshot(found)]

    response = client.post(
        "/cache/conversations/batch",
        json={"ids": [hit, negative, found, found, missing]},
    )

    assert response.status_code == 200
    assert response.json() == {
        hit: snapshot(hit),
        negative: None,
        found: snapshot(found),
        missing: None,
    }
    assert read_pipe.get.call_count == 4
    db.execute.assert_awaited_once()
    statement = db.execute.await_args.args[0]
    assert list(statement.compile().params.values()) == [[found, missing]]
    writes = {call.args[0]: call for call in write_pipe.set.call_args_list}
    assert set(writes) == {
        cache._conversation_key(found),
        cache._conversation_key(missing),
    }
    assert writes[cache._conversation_key(missing)].args[1] == "null"
    assert 30 <= writes[cache._conversation_key(missing)].kwargs["ex"] <= 35
    assert 300 <= writes[cache._conversation_key(found)].kwargs["ex"] <= 360
    assert all(
        call.kwargs == {"transaction": False} for call in redis.pipeline.call_args_list
    )


def test_hot_cache_lock_contention_does_not_fall_through_to_database(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    redis.set.return_value = False

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}/hot")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    db.execute.assert_not_awaited()
    redis.eval.assert_not_awaited()
    redis.delete.assert_not_awaited()


def test_hot_cache_expired_lease_uses_guarded_fill_and_release_with_same_token(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    redis.eval.side_effect = [0, 0]  # Another owner has replaced the expired lease.

    response = client.get(f"/cache/conversations/{IDENTIFIERS[0]}/hot")

    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["X-Cache"] == "MISS"
    db.execute.assert_awaited_once()
    redis.set.assert_awaited_once()  # No unguarded data SET after lease loss.
    lock_key, token = redis.set.await_args.args
    assert redis.set.await_args.kwargs == {"nx": True, "ex": cache.LOCK_TTL_SECONDS}
    fill, release = redis.eval.await_args_list
    assert fill.args[:5] == (
        cache._FILL_IF_LOCK_OWNER,
        2,
        lock_key,
        cache._conversation_key(IDENTIFIERS[0]),
        token,
    )
    assert release.args == (cache._RELEASE_LOCK, 1, lock_key, token)
    redis.delete.assert_not_awaited()


def test_hot_cache_database_failure_releases_lock_without_filling_cache(
    client: TestClient, redis: MagicMock, db: MagicMock
) -> None:
    db.execute.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.get(f"/cache/conversations/{IDENTIFIERS[0]}/hot")

    lock_key, token = redis.set.await_args.args
    redis.eval.assert_awaited_once_with(cache._RELEASE_LOCK, 1, lock_key, token)
    redis.delete.assert_not_awaited()


def test_rate_limit_rejection_exposes_retry_delay(
    client: TestClient, redis: MagicMock
) -> None:
    redis.eval.return_value = [0, 5, 1201]

    response = client.post("/cache/rate-limit/demo")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_success_reports_remaining_budget(
    client: TestClient, redis: MagicMock
) -> None:
    redis.eval.return_value = [1, 2, 59_000]

    response = client.post("/cache/rate-limit/demo")

    assert response.status_code == 200
    assert response.json() == {
        "allowed": True,
        "count": 2,
        "remaining": 3,
        "reset_after_ms": 59_000,
    }
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "3"


def test_rate_limit_refuses_counter_without_expiration(
    client: TestClient, redis: MagicMock
) -> None:
    redis.eval.return_value = [0, 5, -1]

    response = client.post("/cache/rate-limit/demo")

    assert response.status_code == 503
    assert "TTL" in response.json()["detail"]


def test_rate_limit_is_unavailable_when_redis_fails(
    client: TestClient, redis: MagicMock
) -> None:
    redis.eval.side_effect = RedisConnectionError("offline")

    assert client.post("/cache/rate-limit/demo").status_code == 503


@pytest.mark.parametrize("as_bytes", [False, True])
def test_data_structures_use_transaction_and_normalize_readback(
    client: TestClient, redis: MagicMock, db: MagicMock, as_bytes: bool
) -> None:
    def raw(value: str) -> str | bytes:
        return value.encode() if as_bytes else value

    write_pipe = pipeline([1] * 9)
    read_pipe = pipeline(
        [
            {raw("name"): raw("Redis learner"), raw("level"): raw("1")},
            {raw("redis"), raw("postgres")},
            [raw("read-cache-example")],
            [(raw("bob"), 20.0), (raw("alice"), 10.0)],
            60,
        ]
    )
    redis.pipeline.side_effect = [write_pipe, read_pipe]

    response = client.post(f"/cache/structures/{IDENTIFIERS[0]}")

    assert response.status_code == 200
    assert response.json() == {
        "profile": {"name": "Redis learner", "level": "1"},
        "tags": ["postgres", "redis"],
        "recent": ["read-cache-example"],
        "leaderboard": [["bob", 20.0], ["alice", 10.0]],
        "ttl_seconds": 60,
    }
    assert [call.kwargs for call in redis.pipeline.call_args_list] == [
        {"transaction": True},
        {"transaction": False},
    ]
    write_pipe.execute.assert_awaited_once()
    read_pipe.execute.assert_awaited_once()
    assert write_pipe.expire.call_count == 4
    assert all(call.args[1] == 60 for call in write_pipe.expire.call_args_list)
    assert write_pipe.ltrim.call_args.args[1:] == (0, 9)
    db.execute.assert_not_awaited()


def test_production_rejects_examples_before_using_services(
    client: TestClient, redis: MagicMock, db: MagicMock, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(cache.settings.app, "env", "prod")

    assert client.get(f"/cache/conversations/{IDENTIFIERS[0]}").status_code == 404
    assert client.post("/cache/rate-limit/demo").status_code == 404
    db.execute.assert_not_awaited()
    redis.get.assert_not_awaited()
    redis.eval.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/cache/conversations/not-a-uuid", None),
        ("PATCH", f"/cache/conversations/{IDENTIFIERS[0]}", {"title": "  "}),
        ("PATCH", f"/cache/conversations/{IDENTIFIERS[0]}", {"title": "x", "extra": 1}),
        ("POST", "/cache/conversations/batch", {"ids": []}),
        ("POST", "/cache/conversations/batch", {"ids": [IDENTIFIERS[0]] * 51}),
        ("POST", "/cache/rate-limit/invalid!", None),
    ],
)
def test_invalid_inputs_are_rejected_before_service_operations(
    client: TestClient,
    redis: MagicMock,
    db: MagicMock,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    assert client.request(method, path, json=body).status_code == 422
    db.execute.assert_not_awaited()
    redis.get.assert_not_awaited()
    redis.set.assert_not_awaited()
    redis.eval.assert_not_awaited()
    redis.pipeline.assert_not_called()
