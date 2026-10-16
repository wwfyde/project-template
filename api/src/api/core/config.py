from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Tuple, Type
from urllib.parse import quote

import httpx2
from pydantic import (
    MISSING,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    computed_field,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)
from redis_fastapi import RedisSettings
from sqlalchemy.engine import URL

from api.agents.config import AgentsConfig
from api.core.telemetry_config import OtelConfig


class RedisConfig(RedisSettings):
    """SDK fields and validation, resolved once by the application's Settings."""

    model_config = SettingsConfigDict(env_file=None)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


class PostgresConfig(BaseModel):
    host: str
    port: int
    username: str
    password: SecretStr
    database: str
    pool_size: int = 30


class AliyunOssConfig(BaseModel):
    bucket_name: str
    region: str | None = None
    access_key_id: str
    access_key_secret: str
    endpoint: str | None = None
    prefix: str = Field("tmp", validation_alias=AliasChoices("prefix", "path_prefix"))
    role_arn: str | None = None


class NacosConfig(BaseModel):
    namespace_id: str
    service_name: str
    server_address: str
    ip: str
    port: int
    username: str
    password: str
    group_name: str


class Model(BaseModel):
    """Describes an OpenAI model offering that can be used with the API."""

    id: str
    """The model identifier, which can be referenced in the API endpoints."""

    created: int
    """The Unix timestamp (in seconds) when the model was created."""

    object: Literal["model"]
    """The object type, which is always "model"."""

    owned_by: str
    """The organization that owns the model."""


class LLMConfig(BaseModel):
    base_url: str
    api_key: SecretStr
    model: str | None = None
    image_model: str | None = None
    models: list[str] | list[Model] = []
    max_tokens: int | None = None
    temperature: float | None = None

    model_config = ConfigDict(
        extra="allow",
    )


class GoogleLLMConfig(LLMConfig):
    use_vertexai: bool = False
    vertex_api_key: SecretStr | None = None


class LLMProvider(BaseModel):
    dashscope: LLMConfig | None = Field(
        default=None, validation_alias=AliasChoices("dashscope", "qwen")
    )
    volcengine: LLMConfig | None = Field(
        default=None, validation_alias=AliasChoices("volcengine", "ark")
    )
    openai: LLMConfig | None = None
    google: GoogleLLMConfig | None = Field(
        default=None, validation_alias=AliasChoices("google", "gemini")
    )
    anthropic: LLMConfig | None = None
    deepseek: LLMConfig | None = None
    openrouter: LLMConfig | None = None
    evolink: LLMConfig | None = None


class SolutionConfig(BaseModel):
    pass


class AppConfig(BaseModel):
    name: str = "api"
    env: Literal["dev", "prod", "local"] = "dev"
    debug: bool = True
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class ExtraSettings(BaseSettings):
    a: str | MISSING = MISSING
    model_config = SettingsConfigDict(
        extra="ignore",
        validate_assignment=True,  # 允许赋值时验证
        env_nested_delimiter="_",
        env_nested_max_split=1,
        toml_file=["config/extra.toml"],
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # The order of the returned callables decides the priority of inputs; first item is the highest priority.
        # 第一个优先级最高
        return (TomlConfigSettingsSource(settings_cls),)


class Settings(BaseSettings):
    # app_name: str = "ai-tools"
    project_name: str = "Api"
    repo_type: Literal["in-memory", "postgres", "mongodb", "mysql", "redis"] = (
        "in-memory"
    )
    profile: Literal["web", "cli", "desktop", "app"] = Field(
        default="web", title="执行环境"
    )
    api_key_header: str = "fastapi"
    admin_users: list[str] = []
    app: AppConfig = Field(default_factory=AppConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    otel: OtelConfig = Field(default_factory=OtelConfig)
    httpx_timeout: int = 60
    wait_max_seconds: int = 60 * 2
    project_dir: Path = Path(__file__).parent.parent.parent.parent
    base_dir: Path = Path.cwd()
    data_dir: Path = base_dir.joinpath("data")
    temp_dir: Path = base_dir.joinpath("temp")
    static_dir: Path = base_dir.joinpath("web", "dist")
    oss: AliyunOssConfig | None = None
    nacos: NacosConfig | None = None
    api_prefix: str | None = None
    proxy_url: str | None = None
    redis: RedisConfig | None = Field(default_factory=RedisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)

    providers: LLMProvider = Field(default_factory=LLMProvider, title="LLM提供商配置")
    # solutions: SolutionConfig | None = Field(None, title="解决方案配置")
    # apps: Any | None = Field(None, title="多应用配置")
    tools: Any | None = Field(None, title="私有化部署工具")
    extra: ExtraSettings = Field(default_factory=ExtraSettings)

    # ark: ArkConfig = None

    @computed_field
    @property
    def redis_dsn(self) -> str:
        if self.redis is None or self.redis.sentinel:
            return ""
        if self.redis.url:
            return self.redis.url
        scheme = "rediss" if self.redis.ssl else "redis"
        username = quote(self.redis.username or "", safe="")
        password = (
            quote(self.redis.password.get_secret_value(), safe="")
            if self.redis.password is not None
            else ""
        )
        auth = f"{username}:{password}@" if username or password else ""
        host = self.redis.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{scheme}://{auth}{host}:{self.redis.port}/{self.redis.db}"

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=[
            ".env",
            ".env.dev",
            ".env.staging",
            ".env.prod",
            ".env.local",
            ".env.dev.local",
            ".env.staging.local",
            ".env.prod.local",
        ],
        env_file_encoding="utf-8",
        validate_assignment=True,  # 允许赋值时验证
        env_nested_delimiter="_",
        env_nested_max_split=1,
        toml_file=[
            "config.toml",
            "config.dev.toml",
            "config.staging.toml",
            "config.prod.toml",
            "config.local.toml",
            "config.dev.local.toml",
            "config.staging.local.toml",
            "config.prod.local.toml",
        ],
        # yaml_file=[
        #     "config.yml",
        #     "config.dev.yml",
        #     "config.staging.yml",
        #     "config.prod.yml",
        #     "config.local.yml",
        #     "config.dev.local.yml",
        #     "config.staging.local.yml",
        #     "config.prod.local.yml",
        # ],
        # yaml_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # The order of the returned callables decides the priority of inputs; first item is the highest priority.
        # 第一个优先级最高
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    # @computed_field  # this is not serializable filed
    @property
    def http_client(self) -> httpx2.Client:
        return httpx2.Client(proxy=self.proxy_url or None)

    # @computed_field  # this is not serializable filed
    @property
    def http_client_async(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(proxy=self.proxy_url or None)

    @computed_field
    @property
    def postgres_dsn(self) -> str:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres.username,
            password=self.postgres.password.get_secret_value(),
            host=self.postgres.host,
            port=self.postgres.port,
            database=self.postgres.database,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(extra=ExtraSettings())


settings: Settings = get_settings()

if __name__ == "__main__":
    settings = get_settings()
    print(settings.redis_dsn)
    print(getattr(getattr(settings.providers, "volcengine", None), "image_model", None))
    print(
        settings.providers.volcengine.api_key if settings.providers.volcengine else None
    )
    print(project_dir := settings.project_dir)
    print(settings.proxy_url)
    # print(settings.play_some())
    print(getattr(settings.providers, "volcengine").base_url)
    print(settings.model_dump_json(exclude_unset=True))
