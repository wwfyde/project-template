"""Application-owned OTel configuration, loaded by Settings from TOML or OTEL_*.

OTLP uses HTTP/protobuf; the collector fans out to Tempo, Prometheus and Loki.
"""

from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator


def parse_key_values(value: str) -> dict[str, str]:
    """Parse the OTel comma-separated key=value format, including URL escapes."""
    result = {}
    for item in value.split(","):
        if not item.strip():
            continue
        key, separator, entry = item.partition("=")
        if not separator or not key.strip():
            raise ValueError("Expected comma-separated key=value pairs")
        result[unquote(key.strip())] = unquote(entry.strip())
    return result


class OtelConfig(BaseModel):
    enabled: bool = False
    sdk_disabled: bool = False
    service_name: str = Field(default="project-template-api", min_length=1)
    service_namespace: str = "project-template"
    service_version: str | None = None
    deployment_environment: str | None = None
    resource_attributes: str = ""
    exporter_otlp_protocol: Literal["http/protobuf"] = "http/protobuf"
    exporter_otlp_endpoint: str = "http://localhost:4318"
    exporter_otlp_traces_endpoint: str | None = None
    exporter_otlp_metrics_endpoint: str | None = None
    exporter_otlp_logs_endpoint: str | None = None
    exporter_otlp_headers: SecretStr = SecretStr("")
    exporter_otlp_timeout: float = Field(default=10, gt=0, le=60)
    traces_enabled: bool = True
    metrics_enabled: bool = True
    logs_enabled: bool = True
    logs_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    fastapi_enabled: bool = True
    postgres_enabled: bool = True
    traces_sampler: Literal[
        "parentbased_traceidratio",
        "parentbased_always_on",
        "traceidratio",
        "always_on",
        "always_off",
    ] = "parentbased_traceidratio"
    traces_sampler_arg: float = Field(default=1.0, ge=0, le=1)
    metric_export_interval: int = Field(default=60000, ge=1000)
    metric_export_timeout: int = Field(default=10000, ge=1000)
    excluded_urls: str = r"/api/health(?:\?.*)?$"

    @property
    def active(self) -> bool:
        return self.enabled and not self.sdk_disabled

    @field_validator(
        "exporter_otlp_endpoint",
        "exporter_otlp_traces_endpoint",
        "exporter_otlp_metrics_endpoint",
        "exporter_otlp_logs_endpoint",
    )
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("OTLP endpoint must be an absolute HTTP(S) URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(
                "Use exporter_otlp_headers for authentication; endpoint must not contain credentials, query, or fragment"
            )
        return value.rstrip("/")

    @field_validator("resource_attributes")
    @classmethod
    def validate_attributes(cls, value: str) -> str:
        parse_key_values(value)
        return value

    def endpoint(self, signal: Literal["traces", "metrics", "logs"]) -> str:
        override = getattr(self, f"exporter_otlp_{signal}_endpoint")
        return override or f"{self.exporter_otlp_endpoint.rstrip('/')}/v1/{signal}"
