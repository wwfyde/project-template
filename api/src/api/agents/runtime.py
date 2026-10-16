"""Composition root: settings choose adapters; services depend only on protocols."""

from api.agents.contracts import AgentBackend, AgentFailure, SessionStore
from api.agents.service import AgentService
from api.agents.store import InMemorySessionStore, PostgresSessionStore
from api.core.config import Settings


def create_agent_service(settings: Settings) -> AgentService:
    store: SessionStore
    if settings.repo_type == "in-memory":
        store = InMemorySessionStore()
    elif settings.repo_type == "postgres":
        from api.core.db import AsyncSessionLocal

        store = PostgresSessionStore(AsyncSessionLocal)
    else:
        raise AgentFailure(
            "unsupported_store", "Agents support in-memory or postgres storage.", 503
        )

    backends: dict[str, AgentBackend] = {}
    provider = settings.providers.openai
    if provider is not None:
        from api.agents.backends.openai_agents import OpenAIAgentsBackend

        backend = OpenAIAgentsBackend.from_config(
            api_key=provider.api_key.get_secret_value(),
            base_url=provider.base_url,
            default_model=provider.model,
            timeout=settings.httpx_timeout,
            proxy_url=settings.proxy_url,
            tracing_disabled=not settings.agents.tracing_enabled,
        )
        backends[backend.name] = backend
    return AgentService(
        backends=backends,
        store=store,
        default_backend=settings.agents.default_backend,
        run_timeout_seconds=settings.agents.run_timeout_seconds,
    )
