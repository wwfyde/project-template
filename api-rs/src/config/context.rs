use std::collections::HashMap;

use anyhow::{Result, ensure};
use percent_encoding::percent_decode_str;
use serde::{Deserialize, Deserializer};
use url::Url;

use super::{LogLevel, SecretString};

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct RequestContextConfig {
    pub enabled: bool,
    pub request_id_header: String,
    pub user_id_header: String,
    pub tenant_id_header: String,
    pub accept_request_id: bool,
    pub expose_identity_headers: bool,
    pub log_requests: bool,
}

impl Default for RequestContextConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            request_id_header: "Request-ID".into(),
            user_id_header: "User-ID".into(),
            tenant_id_header: "Tenant-ID".into(),
            accept_request_id: true,
            expose_identity_headers: true,
            log_requests: true,
        }
    }
}

impl RequestContextConfig {
    pub fn validate(&self) -> Result<()> {
        const RESERVED_HEADERS: &[&str] = &[
            "authorization",
            "cookie",
            "set-cookie",
            "host",
            "connection",
            "content-type",
            "content-length",
            "transfer-encoding",
            "keep-alive",
            "upgrade",
            "cache-control",
            "vary",
            "location",
            "www-authenticate",
            "traceparent",
            "tracestate",
        ];
        for header in [
            &self.request_id_header,
            &self.user_id_header,
            &self.tenant_id_header,
        ] {
            ensure!(
                (1..=64).contains(&header.len())
                    && http::HeaderName::from_bytes(header.as_bytes()).is_ok()
                    && !RESERVED_HEADERS.contains(&header.to_ascii_lowercase().as_str()),
                "Correlation headers must use valid, dedicated HTTP names"
            );
        }
        ensure!(
            !self.request_id_header.eq_ignore_ascii_case("Account-ID")
                && !self.user_id_header.eq_ignore_ascii_case("Account-ID"),
            "Account-ID is reserved for the account context"
        );
        ensure!(
            !self
                .request_id_header
                .eq_ignore_ascii_case(&self.user_id_header)
                && !self
                    .request_id_header
                    .eq_ignore_ascii_case(&self.tenant_id_header)
                && !self
                    .user_id_header
                    .eq_ignore_ascii_case(&self.tenant_id_header),
            "Correlation header names must be distinct"
        );
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
pub enum OtelProtocol {
    #[default]
    #[serde(rename = "http/protobuf")]
    HttpProtobuf,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TracesSampler {
    #[default]
    #[serde(rename = "parentbased_traceidratio")]
    ParentBasedTraceIdRatio,
    #[serde(rename = "parentbased_always_on")]
    ParentBasedAlwaysOn,
    #[serde(rename = "traceidratio")]
    TraceIdRatio,
    AlwaysOn,
    AlwaysOff,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OtelSignal {
    Traces,
    Metrics,
    Logs,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct OtelConfig {
    pub enabled: bool,
    pub sdk_disabled: bool,
    pub service_name: String,
    pub service_namespace: String,
    pub service_version: Option<String>,
    pub deployment_environment: Option<String>,
    pub resource_attributes: String,
    pub exporter_otlp_protocol: OtelProtocol,
    #[serde(deserialize_with = "deserialize_endpoint")]
    pub exporter_otlp_endpoint: String,
    #[serde(deserialize_with = "deserialize_optional_endpoint")]
    pub exporter_otlp_traces_endpoint: Option<String>,
    #[serde(deserialize_with = "deserialize_optional_endpoint")]
    pub exporter_otlp_metrics_endpoint: Option<String>,
    #[serde(deserialize_with = "deserialize_optional_endpoint")]
    pub exporter_otlp_logs_endpoint: Option<String>,
    pub exporter_otlp_headers: SecretString,
    pub exporter_otlp_timeout: f64,
    pub traces_enabled: bool,
    pub metrics_enabled: bool,
    pub logs_enabled: bool,
    pub logs_level: LogLevel,
    pub fastapi_enabled: bool,
    pub postgres_enabled: bool,
    pub traces_sampler: TracesSampler,
    pub traces_sampler_arg: f64,
    pub metric_export_interval: u64,
    pub metric_export_timeout: u64,
    pub excluded_urls: String,
}

impl Default for OtelConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            sdk_disabled: false,
            service_name: "project-template-api".into(),
            service_namespace: "project-template".into(),
            service_version: None,
            deployment_environment: None,
            resource_attributes: String::new(),
            exporter_otlp_protocol: OtelProtocol::HttpProtobuf,
            exporter_otlp_endpoint: "http://localhost:4318".into(),
            exporter_otlp_traces_endpoint: None,
            exporter_otlp_metrics_endpoint: None,
            exporter_otlp_logs_endpoint: None,
            exporter_otlp_headers: SecretString::default(),
            exporter_otlp_timeout: 10.0,
            traces_enabled: true,
            metrics_enabled: true,
            logs_enabled: true,
            logs_level: LogLevel::Info,
            fastapi_enabled: true,
            postgres_enabled: true,
            traces_sampler: TracesSampler::ParentBasedTraceIdRatio,
            traces_sampler_arg: 1.0,
            metric_export_interval: 60000,
            metric_export_timeout: 10000,
            excluded_urls: r"/api/health(?:\?.*)?$".into(),
        }
    }
}

impl OtelConfig {
    pub fn active(&self) -> bool {
        self.enabled && !self.sdk_disabled
    }

    pub fn endpoint(&self, signal: OtelSignal) -> String {
        let (name, endpoint) = match signal {
            OtelSignal::Traces => ("traces", &self.exporter_otlp_traces_endpoint),
            OtelSignal::Metrics => ("metrics", &self.exporter_otlp_metrics_endpoint),
            OtelSignal::Logs => ("logs", &self.exporter_otlp_logs_endpoint),
        };
        endpoint
            .as_ref()
            .filter(|value| !value.is_empty())
            .cloned()
            .unwrap_or_else(|| {
                format!(
                    "{}/v1/{name}",
                    self.exporter_otlp_endpoint.trim_end_matches('/')
                )
            })
    }

    pub fn validate(&self) -> Result<()> {
        ensure!(
            !self.service_name.is_empty(),
            "otel.service_name must not be empty"
        );
        validate_endpoint(&self.exporter_otlp_endpoint)?;
        for endpoint in [
            &self.exporter_otlp_traces_endpoint,
            &self.exporter_otlp_metrics_endpoint,
            &self.exporter_otlp_logs_endpoint,
        ]
        .into_iter()
        .flatten()
        {
            validate_endpoint(endpoint)?;
        }
        parse_key_values(&self.resource_attributes)?;
        ensure!(
            self.exporter_otlp_timeout > 0.0 && self.exporter_otlp_timeout <= 60.0,
            "otel.exporter_otlp_timeout must be greater than 0 and at most 60"
        );
        ensure!(
            (0.0..=1.0).contains(&self.traces_sampler_arg),
            "otel.traces_sampler_arg must be between 0 and 1"
        );
        ensure!(
            self.metric_export_interval >= 1000 && self.metric_export_timeout >= 1000,
            "OTel metric export interval and timeout must be at least 1000 milliseconds"
        );
        Ok(())
    }
}

fn validate_endpoint(value: &str) -> Result<()> {
    let url = Url::parse(value)
        .map_err(|_| anyhow::anyhow!("OTLP endpoint must be an absolute HTTP(S) URL"))?;
    let authority = value.split_once("://").map(|(_, rest)| rest);
    ensure!(
        matches!(url.scheme(), "http" | "https")
            && url.host_str().is_some()
            && authority.is_some_and(|rest| !rest.is_empty() && !rest.starts_with('/')),
        "OTLP endpoint must be an absolute HTTP(S) URL"
    );
    ensure!(
        url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none(),
        "Use exporter_otlp_headers for authentication; endpoint must not contain credentials, query, or fragment"
    );
    Ok(())
}

fn deserialize_endpoint<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    let value = String::deserialize(deserializer)?;
    validate_endpoint(&value).map_err(serde::de::Error::custom)?;
    Ok(value.trim_end_matches('/').into())
}

fn deserialize_optional_endpoint<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    Option::<String>::deserialize(deserializer)?
        .map(|value| {
            validate_endpoint(&value).map_err(serde::de::Error::custom)?;
            Ok(value.trim_end_matches('/').into())
        })
        .transpose()
}

/// Parse OTel's comma-separated key=value format, preserving '=' in values.
pub fn parse_key_values(value: &str) -> Result<HashMap<String, String>> {
    let mut attributes = HashMap::new();
    for item in value.split(',').filter(|item| !item.trim().is_empty()) {
        let (key, entry) = item
            .split_once('=')
            .ok_or_else(|| anyhow::anyhow!("Expected comma-separated key=value pairs"))?;
        ensure!(
            !key.trim().is_empty(),
            "Expected comma-separated key=value pairs"
        );
        attributes.insert(
            percent_decode_str(key.trim())
                .decode_utf8_lossy()
                .into_owned(),
            percent_decode_str(entry.trim())
                .decode_utf8_lossy()
                .into_owned(),
        );
    }
    Ok(attributes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn correlation_headers_reject_collisions_and_allow_account_tenant_header() {
        for input in [
            json!({"request_id_header": "user-id"}),
            json!({"user_id_header": "Account-ID"}),
            json!({"tenant_id_header": "Authorization"}),
            json!({"request_id_header": "bad\r\nheader"}),
        ] {
            let config: RequestContextConfig = serde_json::from_value(input).unwrap();
            assert!(config.validate().is_err());
        }
        let config: RequestContextConfig = serde_json::from_value(json!({
            "tenant_id_header": "Account-ID"
        }))
        .unwrap();
        config.validate().unwrap();
    }

    #[test]
    fn telemetry_uses_signal_overrides_and_explicit_disable() {
        let mut config: OtelConfig = serde_json::from_value(json!({
            "enabled": true,
            "exporter_otlp_endpoint": "https://collector.example/otlp/",
            "exporter_otlp_logs_endpoint": "https://logs.example/receive/"
        }))
        .unwrap();
        config.validate().unwrap();
        assert!(config.active());
        assert_eq!(
            config.exporter_otlp_endpoint,
            "https://collector.example/otlp"
        );
        assert_eq!(
            config.endpoint(OtelSignal::Traces),
            "https://collector.example/otlp/v1/traces"
        );
        assert_eq!(
            config.endpoint(OtelSignal::Logs),
            "https://logs.example/receive"
        );
        config.sdk_disabled = true;
        assert!(!config.active());
    }

    #[test]
    fn invalid_telemetry_configuration_is_rejected() {
        for value in [
            "http://username:password@collector.example",
            "http://collector.example/?token=secret",
            "http://collector.example/#fragment",
            "grpc://collector.example",
            "collector.example",
            "http:collector.example",
            "http:///collector.example",
        ] {
            assert!(
                serde_json::from_value::<OtelConfig>(json!({
                    "exporter_otlp_endpoint": value
                }))
                .is_err()
            );
        }
        for input in [
            json!({"traces_sampler_arg": -0.1}),
            json!({"traces_sampler_arg": 1.1}),
            json!({"exporter_otlp_timeout": 0}),
            json!({"metric_export_interval": 999}),
            json!({"resource_attributes": "invalid"}),
        ] {
            let config: OtelConfig = serde_json::from_value(input).unwrap();
            assert!(config.validate().is_err());
        }
        for input in [
            json!({"exporter_otlp_protocol": "grpc"}),
            json!({"traces_sampler": "unknown"}),
            json!({"logs_level": "info"}),
        ] {
            assert!(serde_json::from_value::<OtelConfig>(input).is_err());
        }
    }

    #[test]
    fn otel_attributes_decode_escapes_and_use_last_duplicate() {
        let attributes =
            parse_key_values("name=old,,name=hello%20world,escaped%2Ckey=a=b").unwrap();
        assert_eq!(attributes["name"], "hello world");
        assert_eq!(attributes["escaped,key"], "a=b");
        assert!(parse_key_values("=value").is_err());
    }
}
