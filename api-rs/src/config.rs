//! Python `api.core.config.Settings` 的 Rust 配置模型。
//! 单字段默认值由加载器的 set_default 提供；嵌套类型保留各自的 Default 实现。

mod auth;
mod context;
mod loader;
mod redis;

pub use auth::*;
pub use context::*;
pub use loader::load_config;
pub use redis::*;

use std::collections::BTreeMap;
use std::fmt;
use std::path::PathBuf;

use anyhow::{Context, Result, ensure};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;
use url::Url;

/// 与 Pydantic SecretStr 一样，调试和序列化时隐藏凭据。
#[derive(Clone, Default, Deserialize)]
#[serde(transparent)]
pub struct SecretString(String);

impl SecretString {
    pub fn expose_secret(&self) -> &str {
        &self.0
    }
}

impl From<String> for SecretString {
    fn from(value: String) -> Self {
        Self(value)
    }
}

impl From<&str> for SecretString {
    fn from(value: &str) -> Self {
        Self(value.into())
    }
}

impl fmt::Debug for SecretString {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("SecretString(\"**********\")")
    }
}

impl Serialize for SecretString {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        serializer.serialize_str(if self.0.is_empty() { "" } else { "**********" })
    }
}

#[derive(Debug, Default, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RepoType {
    #[default]
    Memory,
    Postgres,
    Mongodb,
    Mysql,
    Redis,
}

#[derive(Debug, Default, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Profile {
    #[default]
    Web,
    Cli,
    Desktop,
    App,
}

#[derive(Debug, Default, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AppEnv {
    #[default]
    Dev,
    Prod,
    Local,
}

#[derive(Debug, Default, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum LogLevel {
    Debug,
    #[default]
    Info,
    Warning,
    Error,
    Critical,
}

#[derive(Clone, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    pub name: String,
    pub env: AppEnv,
    pub debug: bool,
    pub port: u16,
    pub log_level: LogLevel,
    // 旧 Rust 服务的认证扩展；Python Settings 不要求它们，启动服务时单独校验。
    pub api_key: Option<SecretString>,
    pub jwt_secret: Option<SecretString>,
    pub access_token_expire_days: Option<i64>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            name: "api".into(),
            env: AppEnv::Dev,
            debug: true,
            port: 8000,
            log_level: LogLevel::Info,
            api_key: None,
            jwt_secret: None,
            access_token_expire_days: None,
        }
    }
}

impl AppConfig {
    pub fn runtime_auth(&self) -> Result<(String, String, i64)> {
        let api_key = self.api_key.as_ref().context("app.api_key is required")?;
        let jwt_secret = self
            .jwt_secret
            .as_ref()
            .context("app.jwt_secret is required")?;
        let days = self
            .access_token_expire_days
            .context("app.access_token_expire_days is required")?;
        ensure!(
            !api_key.expose_secret().trim().is_empty(),
            "app.api_key is required"
        );
        ensure!(
            !jwt_secret.expose_secret().trim().is_empty(),
            "app.jwt_secret is required"
        );
        ensure!(
            days > 0
                && chrono::Duration::try_days(days)
                    .and_then(|duration| chrono::Utc::now().checked_add_signed(duration))
                    .is_some(),
            "app.access_token_expire_days must be a positive, representable duration"
        );
        Ok((
            api_key.expose_secret().into(),
            jwt_secret.expose_secret().into(),
            days,
        ))
    }
}

/// 兼容已有 Rust 类型名。
pub type App = AppConfig;

#[derive(Clone, Deserialize)]
pub struct PostgresConfig {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub password: SecretString,
    #[serde(alias = "database")]
    pub db: String,
    pub pool_size: u32,
}

impl PostgresConfig {
    /// 凭据、数据库名称分别编码，保留 Rust 数据库驱动所需的 postgresql scheme。
    pub fn connection_url(&self) -> Result<Url> {
        let mut url = Url::parse("postgresql://localhost")?;
        let host = if self.host.contains(':') && !self.host.starts_with('[') {
            format!("[{}]", self.host)
        } else {
            self.host.clone()
        };
        url.set_host(Some(&host)).context("invalid postgres host")?;
        url.set_port(Some(self.port))
            .map_err(|_| anyhow::anyhow!("invalid postgres port"))?;
        url.set_username(&utf8_percent_encode(&self.username, NON_ALPHANUMERIC).to_string())
            .map_err(|_| anyhow::anyhow!("invalid postgres username"))?;
        url.set_password(Some(
            &utf8_percent_encode(self.password.expose_secret(), NON_ALPHANUMERIC).to_string(),
        ))
        .map_err(|_| anyhow::anyhow!("invalid postgres password"))?;
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("invalid postgres URL"))?
            .clear()
            .push(&self.db);
        Ok(url)
    }
}

#[derive(Clone, Deserialize)]
pub struct AliyunOssConfig {
    pub bucket_name: String,
    pub region: Option<String>,
    pub access_key_id: String,
    pub access_key_secret: SecretString,
    pub endpoint: Option<String>,
    #[serde(alias = "path_prefix")]
    pub prefix: String,
    pub role_arn: Option<String>,
}

#[derive(Clone, Deserialize)]
pub struct NacosConfig {
    pub namespace_id: String,
    pub service_name: String,
    pub server_address: String,
    pub ip: String,
    pub port: u16,
    pub username: String,
    pub password: SecretString,
    pub group_name: String,
}

#[derive(Debug, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ModelObject {
    Model,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Model {
    pub id: String,
    pub created: i64,
    pub object: ModelObject,
    pub owned_by: String,
}

/// Python 为 list[str] | list[Model]，不能接受字符串/对象混合的列表。
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum Models {
    Names(Vec<String>),
    Descriptions(Vec<Model>),
}

impl Default for Models {
    fn default() -> Self {
        Self::Names(Vec::new())
    }
}

#[derive(Clone, Deserialize)]
pub struct LlmConfig {
    pub base_url: String,
    pub api_key: SecretString,
    pub model: String,
    pub image_model: Option<String>,
    #[serde(default)]
    pub models: Models,
    #[serde(default, deserialize_with = "deserialize_optional_number")]
    pub max_tokens: Option<i64>,
    #[serde(default, deserialize_with = "deserialize_optional_number")]
    pub temperature: Option<f64>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

// Google 的 flatten 会先缓冲 serde 值，需显式保留环境变量中的数值字符串转换。
fn deserialize_optional_number<'de, D, T>(
    deserializer: D,
) -> std::result::Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de> + std::str::FromStr,
    T::Err: fmt::Display,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum NumberOrString<T> {
        Number(T),
        String(String),
    }
    Option::<NumberOrString<T>>::deserialize(deserializer)?
        .map(|value| match value {
            NumberOrString::Number(value) => Ok(value),
            NumberOrString::String(value) => value.parse().map_err(serde::de::Error::custom),
        })
        .transpose()
}

#[derive(Clone, Deserialize)]
pub struct GoogleLlmConfig {
    #[serde(flatten)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub use_vertexai: bool,
    pub vertex_api_key: Option<SecretString>,
}

impl std::ops::Deref for GoogleLlmConfig {
    type Target = LlmConfig;
    fn deref(&self) -> &Self::Target {
        &self.llm
    }
}

#[derive(Clone, Default, Deserialize)]
#[serde(default)]
pub struct LlmProvider {
    #[serde(alias = "qwen")]
    pub dashscope: Option<LlmConfig>,
    #[serde(alias = "ark")]
    pub volcengine: Option<LlmConfig>,
    pub openai: Option<LlmConfig>,
    #[serde(alias = "gemini")]
    pub google: Option<GoogleLlmConfig>,
    pub anthropic: Option<LlmConfig>,
    pub deepseek: Option<LlmConfig>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct AgentConfig {}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SolutionConfig {}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ExtraSettings {
    // MISSING 与 None 不同：允许缺省，但显式 null 必须拒绝。
    #[serde(default, deserialize_with = "deserialize_present_string")]
    pub a: Option<String>,
}

fn deserialize_present_string<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Option<String>, D::Error> {
    String::deserialize(deserializer).map(Some)
}

#[derive(Clone, Deserialize)]
pub struct Settings {
    pub project_name: String,
    #[serde(default)]
    pub repo_type: RepoType,
    #[serde(default)]
    pub profile: Profile,
    #[serde(default)]
    pub admin_users: Vec<String>,
    #[serde(default)]
    pub app: AppConfig,
    #[serde(default)]
    pub agent: AgentConfig,
    #[serde(default)]
    pub auth: AuthConfig,
    #[serde(default)]
    pub request_context: RequestContextConfig,
    #[serde(default)]
    pub otel: OtelConfig,
    pub httpx_timeout: i64,
    pub wait_max_seconds: i64,
    pub project_dir: PathBuf,
    pub base_dir: PathBuf,
    pub data_dir: PathBuf,
    pub temp_dir: PathBuf,
    pub static_dir: PathBuf,
    pub oss: Option<AliyunOssConfig>,
    pub nacos: Option<NacosConfig>,
    pub api_prefix: Option<String>,
    pub proxy_url: Option<String>,
    pub redis: Option<RedisConfig>,
    // Python default_factory 不会为这五个必填字段提供值。
    pub postgres: PostgresConfig,
    #[serde(default)]
    pub providers: LlmProvider,
    pub tools: Option<Value>,
    #[serde(default)]
    pub extra: ExtraSettings,
}

impl Settings {
    pub fn validate(self) -> Result<Self> {
        ensure!(self.postgres.port > 0, "postgres.port must be nonzero");
        ensure!(!self.postgres.db.is_empty(), "postgres.db is required");
        ensure!(
            self.postgres.pool_size > 0,
            "postgres.pool_size must be positive"
        );
        self.postgres.connection_url()?;
        self.auth.validate()?;
        self.request_context.validate()?;
        self.otel.validate()?;
        self.auth
            .validate_context(self.app.env, &self.request_context)?;
        if let Some(redis) = &self.redis {
            redis.validate()?;
        }
        Ok(self)
    }

    pub fn postgres_dsn(&self) -> Result<String> {
        Ok(self.postgres.connection_url()?.into())
    }

    pub fn redis_dsn(&self) -> Result<String> {
        self.redis
            .as_ref()
            .map_or_else(|| Ok(String::new()), RedisConfig::connection_url)
    }
}

#[cfg(test)]
mod tests;
