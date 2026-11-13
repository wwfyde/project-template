use std::collections::HashSet;

use anyhow::{Result, ensure};
use serde::Deserialize;
use url::Url;

use super::{AppEnv, RequestContextConfig, SecretString};

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct GoogleAuthConfig {
    pub enabled: bool,
    pub client_id: String,
    pub client_secret: SecretString,
    pub redirect_uri: String,
    pub scope: String,
    pub timeout_seconds: f64,
}

impl Default for GoogleAuthConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            client_id: String::new(),
            client_secret: SecretString::default(),
            redirect_uri: "http://localhost:8000/api/auth/oauth/google/callback".into(),
            scope: "openid email profile".into(),
            timeout_seconds: 10.0,
        }
    }
}

impl GoogleAuthConfig {
    pub fn ready(&self) -> bool {
        self.enabled
            && !self.client_id.trim().is_empty()
            && !self.client_secret.expose_secret().trim().is_empty()
    }

    pub fn validate(&self) -> Result<()> {
        validate_oauth(&self.redirect_uri, self.timeout_seconds)?;
        ensure!(
            self.scope.split_whitespace().any(|scope| scope == "openid"),
            "Google authentication requires the openid scope"
        );
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DingTalkAuthConfig {
    pub enabled: bool,
    pub client_id: String,
    pub client_secret: SecretString,
    pub redirect_uri: String,
    pub scope: String,
    pub timeout_seconds: f64,
}

impl Default for DingTalkAuthConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            client_id: String::new(),
            client_secret: SecretString::default(),
            redirect_uri: "http://localhost:8000/api/auth/oauth/dingtalk/callback".into(),
            scope: "openid".into(),
            timeout_seconds: 10.0,
        }
    }
}

impl DingTalkAuthConfig {
    pub fn ready(&self) -> bool {
        self.enabled
            && !self.client_id.trim().is_empty()
            && !self.client_secret.expose_secret().trim().is_empty()
    }

    pub fn validate(&self) -> Result<()> {
        validate_oauth(&self.redirect_uri, self.timeout_seconds)
    }
}

fn validate_oauth(redirect_uri: &str, timeout_seconds: f64) -> Result<()> {
    let url = parse_auth_url(redirect_uri, "redirect_uri")?;
    ensure!(
        url.fragment().is_none(),
        "redirect_uri must be an absolute HTTP(S) callback URL"
    );
    ensure!(
        timeout_seconds > 0.0 && timeout_seconds <= 120.0,
        "OAuth timeout_seconds must be greater than 0 and at most 120"
    );
    Ok(())
}

fn parse_auth_url(value: &str, field: &str) -> Result<Url> {
    ensure!(
        !value.contains('\\') && !value.chars().any(|character| (character as u32) < 33),
        "{field} must be an absolute HTTP(S) URL without credentials or whitespace"
    );
    let url = Url::parse(value)
        .map_err(|_| anyhow::anyhow!("{field} must be an absolute HTTP(S) URL"))?;
    let authority = value.split_once("://").map(|(_, rest)| rest);
    ensure!(
        matches!(url.scheme(), "http" | "https")
            && url.host_str().is_some()
            && authority.is_some_and(|rest| !rest.is_empty() && !rest.starts_with('/'))
            && url.username().is_empty()
            && url.password().is_none(),
        "{field} must be an absolute HTTP(S) URL without credentials"
    );
    Ok(url)
}

fn validate_frontend_url(value: &str) -> Result<()> {
    let url = parse_auth_url(value, "frontend_url")?;
    // Inspect the source path too: URL parsers normalize '/..' and '/./' to '/'.
    let raw_path = value
        .split_once("://")
        .and_then(|(_, authority)| authority.find('/').map(|index| &authority[index..]));
    ensure!(
        matches!(raw_path, None | Some("/")) && url.query().is_none() && url.fragment().is_none(),
        "frontend_url must be an HTTP(S) origin without a path"
    );
    Ok(())
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PhoneAuthConfig {
    pub enabled: bool,
}

impl PhoneAuthConfig {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            !self.enabled,
            "Phone authentication is reserved and not implemented"
        );
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PasswordAuthConfig {
    pub enabled: bool,
    pub rate_limit_attempts: u32,
    pub ip_rate_limit_attempts: u32,
    pub rate_limit_window_seconds: u32,
}

impl Default for PasswordAuthConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            rate_limit_attempts: 10,
            ip_rate_limit_attempts: 50,
            rate_limit_window_seconds: 300,
        }
    }
}

impl PasswordAuthConfig {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            (1..=1000).contains(&self.rate_limit_attempts),
            "auth.password.rate_limit_attempts must be between 1 and 1000"
        );
        ensure!(
            (1..=10000).contains(&self.ip_rate_limit_attempts),
            "auth.password.ip_rate_limit_attempts must be between 1 and 10000"
        );
        ensure!(
            (1..=3600).contains(&self.rate_limit_window_seconds),
            "auth.password.rate_limit_window_seconds must be between 1 and 3600"
        );
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct HeaderAuthConfig {
    pub enabled: bool,
    pub name: String,
    pub keys: Vec<SecretString>,
}

impl Default for HeaderAuthConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            name: "X-Api-Key".into(),
            keys: Vec::new(),
        }
    }
}

impl HeaderAuthConfig {
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
            "origin",
            "referer",
            "request-id",
            "user-id",
            "tenant-id",
            "account-id",
            "x-request-id",
            "x-user-id",
            "x-tenant-id",
            "x-csrf-token",
            "traceparent",
            "tracestate",
            "baggage",
        ];
        ensure!(
            (1..=64).contains(&self.name.len())
                && http::HeaderName::from_bytes(self.name.as_bytes()).is_ok()
                && !RESERVED_HEADERS.contains(&self.name.to_ascii_lowercase().as_str()),
            "API keys require a valid, dedicated HTTP header name"
        );
        ensure!(
            self.keys.len() <= 16,
            "auth.header.keys allows at most 16 keys"
        );
        for key in &self.keys {
            let secret = key.expose_secret();
            ensure!(
                (32..=512).contains(&secret.len())
                    && secret.bytes().all(|byte| (33..=126).contains(&byte)),
                "API keys must contain 32 to 512 visible ASCII characters"
            );
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(try_from = "AuthConfigInput")]
pub struct AuthConfig {
    pub providers: Vec<String>,
    pub default_tenant_id: String,
    pub allow_signup: bool,
    pub session_key_prefix: String,
    pub frontend_url: String,
    pub oauth_state_ttl_seconds: u32,
    pub reauth_max_age_seconds: u32,
    pub google: GoogleAuthConfig,
    pub dingtalk: DingTalkAuthConfig,
    pub phone: PhoneAuthConfig,
    pub password: PasswordAuthConfig,
    pub header: HeaderAuthConfig,
}

impl Default for AuthConfig {
    fn default() -> Self {
        Self {
            providers: ["google", "password", "dingtalk", "phone"]
                .map(String::from)
                .into(),
            default_tenant_id: "default".into(),
            allow_signup: true,
            session_key_prefix: "project-template:auth".into(),
            frontend_url: "http://localhost:5173".into(),
            oauth_state_ttl_seconds: 600,
            reauth_max_age_seconds: 300,
            google: GoogleAuthConfig::default(),
            dingtalk: DingTalkAuthConfig::default(),
            phone: PhoneAuthConfig::default(),
            password: PasswordAuthConfig::default(),
            header: HeaderAuthConfig::default(),
        }
    }
}

impl AuthConfig {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.providers.iter().any(|provider| provider == "google"),
            "auth.providers must include google"
        );
        ensure!(
            self.providers.iter().collect::<HashSet<_>>().len() == self.providers.len(),
            "auth.providers must not contain duplicate providers"
        );
        ensure!(
            self.providers.iter().all(|provider| matches!(
                provider.as_str(),
                "google" | "password" | "dingtalk" | "phone"
            )),
            "Unknown authentication provider"
        );
        ensure!(
            (1..=64).contains(&self.default_tenant_id.len())
                && self
                    .default_tenant_id
                    .bytes()
                    .all(|byte| { byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-') }),
            "auth.default_tenant_id must be a 1 to 64 character ASCII identifier"
        );
        ensure!(
            (1..=128).contains(&self.session_key_prefix.chars().count())
                && !self.session_key_prefix.trim().is_empty()
                && !self
                    .session_key_prefix
                    .chars()
                    .any(|character| { (character as u32) < 33 || character == '\u{7f}' }),
            "session_key_prefix cannot contain whitespace or control characters"
        );
        validate_frontend_url(&self.frontend_url)?;
        ensure!(
            (60..=1800).contains(&self.oauth_state_ttl_seconds),
            "auth.oauth_state_ttl_seconds must be between 60 and 1800"
        );
        ensure!(
            (60..=1800).contains(&self.reauth_max_age_seconds),
            "auth.reauth_max_age_seconds must be between 60 and 1800"
        );
        self.google.validate()?;
        self.dingtalk.validate()?;
        self.phone.validate()?;
        self.password.validate()?;
        self.header.validate()?;
        Ok(())
    }

    pub fn validate_context(&self, app_env: AppEnv, context: &RequestContextConfig) -> Result<()> {
        ensure!(
            [
                &context.request_id_header,
                &context.user_id_header,
                &context.tenant_id_header
            ]
            .iter()
            .all(|header| !header.eq_ignore_ascii_case(&self.header.name)),
            "Authentication Header must not be a correlation header"
        );
        if matches!(app_env, AppEnv::Prod) {
            let google =
                self.providers.iter().any(|provider| provider == "google") && self.google.ready();
            let dingtalk = self.providers.iter().any(|provider| provider == "dingtalk")
                && self.dingtalk.ready();
            let password = self.providers.iter().any(|provider| provider == "password")
                && self.password.enabled;
            ensure!(
                !(google || dingtalk || password) || self.frontend_url.starts_with("https://"),
                "Production authentication requires an HTTPS frontend_url"
            );
            ensure!(
                (!google || self.google.redirect_uri.starts_with("https://"))
                    && (!dingtalk || self.dingtalk.redirect_uri.starts_with("https://")),
                "Production authentication requires HTTPS callback URLs"
            );
        }
        Ok(())
    }
}

// Keep legacy values at the input boundary, so obsolete secrets are never retained.
#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct AuthConfigInput {
    providers: Vec<String>,
    default_tenant_id: String,
    allow_signup: bool,
    session_key_prefix: String,
    #[serde(deserialize_with = "deserialize_present_string")]
    frontend_url: Option<String>,
    oauth_state_ttl_seconds: u32,
    reauth_max_age_seconds: u32,
    google: GoogleAuthConfig,
    dingtalk: LegacyDingTalkConfig,
    phone: PhoneAuthConfig,
    password: PasswordAuthConfig,
    header: HeaderAuthConfig,
}

fn deserialize_present_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    String::deserialize(deserializer).map(Some)
}

impl Default for AuthConfigInput {
    fn default() -> Self {
        let config = AuthConfig::default();
        Self {
            providers: config.providers,
            default_tenant_id: config.default_tenant_id,
            allow_signup: config.allow_signup,
            session_key_prefix: config.session_key_prefix,
            frontend_url: None,
            oauth_state_ttl_seconds: config.oauth_state_ttl_seconds,
            reauth_max_age_seconds: config.reauth_max_age_seconds,
            google: config.google,
            dingtalk: LegacyDingTalkConfig::default(),
            phone: config.phone,
            password: config.password,
            header: config.header,
        }
    }
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct LegacyDingTalkConfig {
    enabled: bool,
    client_id: String,
    client_secret: SecretString,
    redirect_uri: String,
    scope: String,
    timeout_seconds: f64,
    frontend_url: Option<String>,
    #[serde(rename = "session_secret")]
    _session_secret: serde::de::IgnoredAny,
}

impl Default for LegacyDingTalkConfig {
    fn default() -> Self {
        let config = DingTalkAuthConfig::default();
        Self {
            enabled: config.enabled,
            client_id: config.client_id,
            client_secret: config.client_secret,
            redirect_uri: config.redirect_uri,
            scope: config.scope,
            timeout_seconds: config.timeout_seconds,
            frontend_url: None,
            _session_secret: serde::de::IgnoredAny,
        }
    }
}

impl TryFrom<AuthConfigInput> for AuthConfig {
    type Error = anyhow::Error;

    fn try_from(input: AuthConfigInput) -> Result<Self> {
        let frontend_url = input
            .frontend_url
            .or(input.dingtalk.frontend_url)
            .unwrap_or_else(|| "http://localhost:5173".into());
        validate_frontend_url(&frontend_url)?;
        Ok(Self {
            providers: input.providers,
            default_tenant_id: input.default_tenant_id,
            allow_signup: input.allow_signup,
            session_key_prefix: input.session_key_prefix,
            frontend_url: frontend_url.trim_end_matches('/').into(),
            oauth_state_ttl_seconds: input.oauth_state_ttl_seconds,
            reauth_max_age_seconds: input.reauth_max_age_seconds,
            google: input.google,
            dingtalk: DingTalkAuthConfig {
                enabled: input.dingtalk.enabled,
                client_id: input.dingtalk.client_id,
                client_secret: input.dingtalk.client_secret,
                redirect_uri: input.dingtalk.redirect_uri,
                scope: input.dingtalk.scope,
                timeout_seconds: input.dingtalk.timeout_seconds,
            },
            phone: input.phone,
            password: input.password,
            header: input.header,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn legacy_dingtalk_values_migrate_without_retaining_unused_secrets() {
        let mut input = json!({"dingtalk": {
            "client_id": "client", "client_secret": "test-secret",
            "frontend_url": "http://localhost:6173/", "session_secret": "obsolete-secret"
        }});
        let config: AuthConfig = serde_json::from_value(input.clone()).unwrap();
        config.validate().unwrap();
        assert_eq!(config.frontend_url, "http://localhost:6173");
        assert!(config.dingtalk.ready());
        assert!(!format!("{config:?}").contains("obsolete-secret"));
        assert!(!format!("{config:?}").contains("test-secret"));
        input["frontend_url"] = json!("https://app.example.test");
        let config: AuthConfig = serde_json::from_value(input).unwrap();
        assert_eq!(config.frontend_url, "https://app.example.test");
    }

    #[test]
    fn production_https_checks_apply_to_available_providers() {
        let mut config = AuthConfig::default();
        let context = RequestContextConfig::default();
        config.validate_context(AppEnv::Prod, &context).unwrap();
        config.google.client_id = "client".into();
        config.google.client_secret = "secret".into();
        assert!(config.validate_context(AppEnv::Prod, &context).is_err());
        config.frontend_url = "https://app.example.test".into();
        assert!(config.validate_context(AppEnv::Prod, &context).is_err());
        config.google.redirect_uri = "https://api.example.test/callback".into();
        config.validate_context(AppEnv::Prod, &context).unwrap();
    }

    #[test]
    fn invalid_authentication_inputs_fail_closed() {
        for input in [
            json!({"providers": []}),
            json!({"providers": ["google", "google"]}),
            json!({"providers": ["google", "unknown"]}),
            json!({"phone": {"enabled": true}}),
            json!({"google": {"scope": "email profile"}}),
            json!({"header": {"name": "Authorization"}}),
            json!({"header": {"keys": ["too-short"]}}),
            json!({"password": {"rate_limit_attempts": 0}}),
        ] {
            let config: AuthConfig = serde_json::from_value(input).unwrap();
            assert!(config.validate().is_err());
        }
        for input in [
            json!({"unknown": true}),
            json!({"google": {"unknown": true}}),
            json!({"dingtalk": {"unknown": true}}),
            json!({"frontend_url": null}),
            json!({"frontend_url": "https://example.test/login"}),
            json!({"frontend_url": "https://example.test//"}),
            json!({"frontend_url": "https://example.test/.."}),
        ] {
            assert!(serde_json::from_value::<AuthConfig>(input).is_err());
        }
        let config = AuthConfig::default();
        let context = RequestContextConfig {
            request_id_header: "x-api-key".into(),
            ..RequestContextConfig::default()
        };
        assert!(config.validate_context(AppEnv::Dev, &context).is_err());
    }
}
