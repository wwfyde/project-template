from pydantic import BaseModel, ConfigDict, Field


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_backend: str = "openai-agents"
    run_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    tracing_enabled: bool = False
