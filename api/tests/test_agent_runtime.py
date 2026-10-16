from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from api.agents.config import AgentsConfig
from api.agents.contracts import AgentFailure, SessionCreate
from api.agents.runtime import create_agent_service
from api.agents.store import InMemorySessionStore, PostgresSessionStore
from api.core.config import LLMConfig, LLMProvider, Settings, settings


@pytest.mark.asyncio
async def test_unconfigured_provider_does_not_require_sdk_credentials() -> None:
    config = settings.model_copy(
        update={"providers": LLMProvider(), "repo_type": "in-memory"}
    )
    service = create_agent_service(config)
    assert isinstance(service.store, InMemorySessionStore)
    assert service.backends == {}
    with pytest.raises(AgentFailure) as error:
        await service.create_session(SessionCreate())
    assert error.value.code == "backend_unavailable"
    assert error.value.status_code == 503
    await service.aclose()


@pytest.mark.asyncio
async def test_runtime_selects_postgres_without_connecting() -> None:
    service = create_agent_service(
        settings.model_copy(
            update={"providers": LLMProvider(), "repo_type": "postgres"}
        )
    )
    assert isinstance(service.store, PostgresSessionStore)
    await service.aclose()


def test_unsupported_store_is_not_silently_replaced_with_memory() -> None:
    with pytest.raises(AgentFailure) as error:
        create_agent_service(settings.model_copy(update={"repo_type": "redis"}))
    assert error.value.code == "unsupported_store"


@pytest.mark.asyncio
async def test_runtime_passes_explicit_provider_and_lifecycle() -> None:
    config = settings.model_copy(
        update={
            "repo_type": "in-memory",
            "providers": LLMProvider(
                openai=LLMConfig(
                    api_key="test-only-key",
                    base_url="https://provider.example/v1",
                    model="configured-model",
                )
            ),
            "agents": AgentsConfig(run_timeout_seconds=42, tracing_enabled=False),
            "proxy_url": "http://proxy.example:8080",
            "httpx_timeout": 23,
        }
    )
    backend = AsyncMock()
    backend.name = "openai-agents"
    with patch(
        "api.agents.backends.openai_agents.OpenAIAgentsBackend.from_config",
        return_value=backend,
    ) as create:
        service = create_agent_service(config)
    create.assert_called_once_with(
        api_key="test-only-key",
        base_url="https://provider.example/v1",
        default_model="configured-model",
        timeout=23,
        proxy_url="http://proxy.example:8080",
        tracing_disabled=True,
    )
    assert service.run_timeout_seconds == 42
    await service.aclose()
    backend.aclose.assert_awaited_once()


def test_agent_settings_environment_overrides_toml(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        '[agents]\ndefault_backend = "custom"\nrun_timeout_seconds = 80\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTS_RUN_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("AGENTS_TRACING_ENABLED", "true")
    config = Settings(postgres=settings.postgres, _env_file=None)
    assert config.agents.default_backend == "custom"
    assert config.agents.run_timeout_seconds == 12
    assert config.agents.tracing_enabled is True


@pytest.mark.parametrize("timeout", [0, -1, 3601])
def test_agent_timeout_configuration_is_bounded(timeout: int) -> None:
    with pytest.raises(ValidationError):
        AgentsConfig(run_timeout_seconds=timeout)
