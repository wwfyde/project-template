use anyhow::{Result, ensure};
use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use serde::{Deserialize, Deserializer, de};

use super::SecretString;

const CREDENTIAL_ENCODE_SET: &AsciiSet = &NON_ALPHANUMERIC
    .remove(b'-')
    .remove(b'.')
    .remove(b'_')
    .remove(b'~');
const DEFAULT_SENTINEL_PORT: u16 = 26379;

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CookieSameSite {
    #[default]
    Lax,
    Strict,
    None,
}

/// Redis SDK settings, including the application's session defaults.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct RedisConfig {
    pub url: Option<String>,
    pub host: String,
    pub port: u16,
    pub db: u64,
    pub username: Option<String>,
    pub password: Option<SecretString>,
    pub ssl: bool,
    pub ssl_certfile: Option<String>,
    pub ssl_keyfile: Option<String>,
    pub ssl_ca_certs: Option<String>,
    pub ssl_check_hostname: bool,
    pub max_connections: Option<u64>,
    pub socket_timeout: Option<f64>,
    pub socket_connect_timeout: Option<f64>,
    pub cluster: bool,
    pub sentinel: bool,
    pub sentinel_master_name: String,
    #[serde(deserialize_with = "deserialize_sentinel_nodes")]
    pub sentinel_nodes: Vec<String>,
    pub sentinel_username: Option<String>,
    pub sentinel_password: Option<SecretString>,
    pub prefix: String,
    pub default_ttl: u64,
    pub warn_unbounded_cache: bool,
    pub rate_limit_default_limit: u64,
    pub rate_limit_default_window: u64,
    pub rate_limit_fail_closed: bool,
    pub rate_limit_emit_headers: bool,
    pub rate_limit_ietf_headers: bool,
    pub session_cookie_name: String,
    pub session_cookie_domain: Option<String>,
    pub session_cookie_path: String,
    pub session_cookie_same_site: CookieSameSite,
    pub session_cookie_https_only: bool,
    pub session_idle_ttl: u64,
    pub session_absolute_ttl: u64,
    pub session_gc_ttl: u64,
    pub session_refresh_on_load: bool,
    pub session_fail_closed: bool,
    pub session_always_save: bool,
    #[serde(deserialize_with = "deserialize_principal_keys")]
    pub session_principal_keys: Vec<String>,
    pub otel_enabled: bool,
    pub otel_redis_enabled: bool,
}

impl Default for RedisConfig {
    fn default() -> Self {
        Self {
            url: None,
            host: "localhost".into(),
            port: 6379,
            db: 0,
            username: None,
            password: None,
            ssl: false,
            ssl_certfile: None,
            ssl_keyfile: None,
            ssl_ca_certs: None,
            ssl_check_hostname: true,
            max_connections: None,
            socket_timeout: None,
            socket_connect_timeout: None,
            cluster: false,
            sentinel: false,
            sentinel_master_name: "mymaster".into(),
            sentinel_nodes: Vec::new(),
            sentinel_username: None,
            sentinel_password: None,
            prefix: "redis:fastapi".into(),
            default_ttl: 0,
            warn_unbounded_cache: true,
            rate_limit_default_limit: 0,
            rate_limit_default_window: 60,
            rate_limit_fail_closed: false,
            rate_limit_emit_headers: true,
            rate_limit_ietf_headers: false,
            session_cookie_name: "project_template_session".into(),
            session_cookie_domain: None,
            session_cookie_path: "/".into(),
            session_cookie_same_site: CookieSameSite::Lax,
            session_cookie_https_only: true,
            session_idle_ttl: 1800,
            session_absolute_ttl: 28800,
            session_gc_ttl: 2592000,
            session_refresh_on_load: true,
            session_fail_closed: true,
            session_always_save: false,
            session_principal_keys: vec!["user_id".into()],
            otel_enabled: false,
            otel_redis_enabled: false,
        }
    }
}

impl RedisConfig {
    pub fn validate(&self) -> Result<()> {
        ensure!(self.port > 0, "redis.port must be between 1 and 65535");
        ensure!(
            self.max_connections.is_none_or(|value| value > 0),
            "redis.max_connections must be positive"
        );
        for (name, timeout) in [
            ("socket_timeout", self.socket_timeout),
            ("socket_connect_timeout", self.socket_connect_timeout),
        ] {
            ensure!(
                timeout.is_none_or(|value| value >= 0.0),
                "redis.{name} must be nonnegative"
            );
        }
        ensure!(
            !self.sentinel_master_name.is_empty(),
            "redis.sentinel_master_name must not be empty"
        );
        ensure!(
            self.rate_limit_default_window > 0,
            "redis.rate_limit_default_window must be positive"
        );
        ensure!(
            self.session_gc_ttl > 0,
            "redis.session_gc_ttl must be positive"
        );
        ensure!(
            !self.session_principal_keys.is_empty(),
            "redis.session_principal_keys must name at least one session key"
        );
        ensure!(
            !self.session_cookie_name.is_empty()
                && self
                    .session_cookie_name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_')),
            "redis.session_cookie_name must contain only letters, digits, '-' and '_'"
        );
        ensure!(
            self.session_cookie_path.starts_with('/')
                && !self
                    .session_cookie_path
                    .bytes()
                    .any(|byte| byte.is_ascii_control() || byte == b';'),
            "redis.session_cookie_path must start with '/' and contain no control characters or ';'"
        );
        if let Some(domain) = &self.session_cookie_domain {
            ensure!(
                !domain.is_empty()
                    && domain
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.')),
                "redis.session_cookie_domain must contain only letters, digits, '-' and '.'"
            );
        }
        if self.sentinel {
            ensure!(
                !self.cluster,
                "redis.sentinel and redis.cluster are mutually exclusive"
            );
            ensure!(
                self.url.is_none(),
                "redis.url is not supported in sentinel mode"
            );
            ensure!(
                !self.sentinel_nodes.is_empty(),
                "redis.sentinel requires at least one sentinel_nodes entry"
            );
            self.sentinel_addresses()?;
        }
        Ok(())
    }

    /// Sentinel supplies the primary address dynamically, so it has no static DSN.
    pub fn connection_url(&self) -> Result<String> {
        if self.sentinel {
            return Ok(String::new());
        }
        if let Some(url) = &self.url
            && !url.is_empty()
        {
            return Ok(url.clone());
        }
        let username = self.username.as_deref().unwrap_or_default();
        let password = self
            .password
            .as_ref()
            .map(SecretString::expose_secret)
            .unwrap_or_default();
        let auth = if username.is_empty() && password.is_empty() {
            String::new()
        } else {
            format!(
                "{}:{}@",
                utf8_percent_encode(username, CREDENTIAL_ENCODE_SET),
                utf8_percent_encode(password, CREDENTIAL_ENCODE_SET)
            )
        };
        let host = if self.host.contains(':') && !self.host.starts_with('[') {
            format!("[{}]", self.host)
        } else {
            self.host.clone()
        };
        let scheme = if self.ssl { "rediss" } else { "redis" };
        Ok(format!("{scheme}://{auth}{host}:{}/{}", self.port, self.db))
    }

    pub fn sentinel_addresses(&self) -> Result<Vec<(String, u16)>> {
        self.sentinel_nodes
            .iter()
            .map(|node| {
                let (host, port) = match node.rsplit_once(':') {
                    Some((host, port)) => (
                        host,
                        port.bytes()
                            .all(|byte| byte.is_ascii_digit())
                            .then(|| port.parse::<u16>().ok())
                            .flatten(),
                    ),
                    None => (node.as_str(), Some(DEFAULT_SENTINEL_PORT)),
                };
                ensure!(
                    !host.is_empty() && port.is_some_and(|value| value > 0),
                    "invalid redis sentinel node; expected host or host:port with port between 1 and 65535"
                );
                Ok((host.to_owned(), port.unwrap_or(DEFAULT_SENTINEL_PORT)))
            })
            .collect()
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum StringList {
    List(Vec<String>),
    Text(String),
}

fn split_csv(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(str::to_owned)
        .collect()
}

fn deserialize_sentinel_nodes<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    Ok(match StringList::deserialize(deserializer)? {
        StringList::List(values) => values,
        StringList::Text(value) => split_csv(&value),
    })
}

fn deserialize_principal_keys<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let values = match StringList::deserialize(deserializer)? {
        StringList::List(values) => values,
        StringList::Text(value) if value.trim().starts_with('[') => {
            serde_json::from_str(&value).map_err(de::Error::custom)?
        }
        StringList::Text(value) => split_csv(&value),
    };
    if values.is_empty() {
        return Err(de::Error::custom(
            "redis.session_principal_keys must name at least one session key",
        ));
    }
    Ok(values)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn partial_configuration_preserves_defaults_and_optional_values() {
        let redis: RedisConfig = serde_json::from_value(json!({ "db": 2 })).unwrap();
        redis.validate().unwrap();
        assert_eq!(redis.connection_url().unwrap(), "redis://localhost:6379/2");
        assert_eq!(redis.session_cookie_name, "project_template_session");
        assert!(redis.session_fail_closed);
        assert!(redis.password.is_none());
        assert!(redis.max_connections.is_none());
        assert_eq!(redis.session_principal_keys, ["user_id"]);
        assert_eq!(redis.session_cookie_same_site, CookieSameSite::Lax);
    }

    #[test]
    fn connection_url_encodes_credentials_and_ipv6_and_honors_overrides() {
        let mut redis = RedisConfig {
            host: "::1".into(),
            username: Some("user_-.~@tenant".into()),
            password: Some("p@ss:/?#%".into()),
            ssl: true,
            ..Default::default()
        };
        assert_eq!(
            redis.connection_url().unwrap(),
            "rediss://user_-.~%40tenant:p%40ss%3A%2F%3F%23%25@[::1]:6379/0"
        );
        redis.url = Some("redis://explicit:6380/4".into());
        assert_eq!(redis.connection_url().unwrap(), "redis://explicit:6380/4");
        redis.sentinel = true;
        assert_eq!(redis.connection_url().unwrap(), "");
    }

    #[test]
    fn sentinel_nodes_and_principal_keys_accept_sdk_input_formats() {
        let redis: RedisConfig = serde_json::from_value(json!({
            "sentinel": true,
            "sentinel_nodes": "redis-a, redis-b:26380,",
            "session_principal_keys": "user_id, role,"
        }))
        .unwrap();
        redis.validate().unwrap();
        assert_eq!(
            redis.sentinel_addresses().unwrap(),
            [("redis-a".into(), 26379), ("redis-b".into(), 26380)]
        );
        assert_eq!(redis.session_principal_keys, ["user_id", "role"]);
        let redis: RedisConfig = serde_json::from_value(json!({
            "session_principal_keys": "[\"user_id\", \"role,scopes\"]"
        }))
        .unwrap();
        assert_eq!(redis.session_principal_keys, ["user_id", "role,scopes"]);
        for value in [json!([]), json!(""), json!("[broken")] {
            assert!(
                serde_json::from_value::<RedisConfig>(json!({"session_principal_keys": value}))
                    .is_err()
            );
        }
    }

    #[test]
    fn rejects_invalid_sentinel_cookie_and_numeric_configuration() {
        for invalid in [
            json!({"sentinel": true}),
            json!({"sentinel": true, "sentinel_nodes": ["redis"], "cluster": true}),
            json!({"sentinel": true, "sentinel_nodes": ["redis"], "url": ""}),
            json!({"sentinel": true, "sentinel_nodes": ["redis:0"]}),
            json!({"sentinel": true, "sentinel_nodes": ["redis:65536"]}),
            json!({"sentinel": true, "sentinel_nodes": ["redis:+26379"]}),
            json!({"sentinel": true, "sentinel_nodes": [":26379"]}),
            json!({"session_cookie_name": "session\r\nInjected"}),
            json!({"session_cookie_path": "/;secure"}),
            json!({"session_cookie_domain": "example.com\r\n"}),
            json!({"port": 0}),
            json!({"max_connections": 0}),
            json!({"socket_timeout": -1}),
            json!({"rate_limit_default_window": 0}),
            json!({"session_gc_ttl": 0}),
        ] {
            let redis: RedisConfig = serde_json::from_value(invalid.clone()).unwrap();
            assert!(redis.validate().is_err(), "accepted {invalid}");
        }
        assert!(
            serde_json::from_value::<RedisConfig>(json!({"session_cookie_same_site": "invalid"}))
                .is_err()
        );
        assert!(serde_json::from_value::<RedisConfig>(json!({"db": -1})).is_err());
    }
}
