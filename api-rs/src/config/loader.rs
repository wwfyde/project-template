use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{Context, Result, anyhow};
use config::{Config, ConfigError, File, FileFormat};
use serde_json::{Map, Value};

use super::Settings;

const TOML_FILES: &[&str] = &[
    "config.toml",
    "config.dev.toml",
    "config.staging.toml",
    "config.prod.toml",
    "config.local.toml",
    "config.dev.local.toml",
    "config.staging.local.toml",
    "config.prod.local.toml",
];
const DOTENV_FILES: &[&str] = &[
    ".env",
    ".env.dev",
    ".env.staging",
    ".env.prod",
    ".env.local",
    ".env.dev.local",
    ".env.staging.local",
    ".env.prod.local",
];
const ROOT_FIELDS: &[&str] = &[
    "project_name",
    "repo_type",
    "profile",
    "admin_users",
    "app",
    "agent",
    "auth",
    "request_context",
    "otel",
    "httpx_timeout",
    "wait_max_seconds",
    "project_dir",
    "base_dir",
    "data_dir",
    "temp_dir",
    "static_dir",
    "oss",
    "nacos",
    "api_prefix",
    "proxy_url",
    "redis",
    "postgres",
    "providers",
    "tools",
];

pub fn load_config() -> Result<Settings> {
    Settings::load_from(
        std::env::current_dir().context("failed to locate the configuration directory")?,
        std::env::vars(),
    )
}

impl Settings {
    /// Apply field defaults to resolved sources before deserializing and validating.
    pub fn from_config(config: Config) -> Result<Self> {
        let base_dir = std::env::current_dir().context("failed to locate the working directory")?;
        let base_dir = base_dir
            .to_str()
            .context("working directory must be valid UTF-8")?;
        let mut builder = Config::builder()
            .set_default("project_name", "Api")?
            .set_default("httpx_timeout", 60)?
            .set_default("wait_max_seconds", 120)?
            .set_default("project_dir", env!("CARGO_MANIFEST_DIR"))?
            .set_default("base_dir", base_dir)?
            .set_default(
                "data_dir",
                Path::new(base_dir).join("data").display().to_string(),
            )?
            .set_default(
                "temp_dir",
                Path::new(base_dir).join("temp").display().to_string(),
            )?
            .set_default(
                "static_dir",
                Path::new(base_dir).join("web/dist").display().to_string(),
            )?
            .set_default("postgres.pool_size", 30)?
            // An empty table uses RedisConfig's defaults; an explicit null source disables Redis.
            .set_default("redis", config::Map::<String, config::Value>::new())?;

        // A default under oss would otherwise instantiate this optional section. Respect its alias
        // as well, including callers that construct Config directly instead of using load_from.
        if let Ok(Value::Object(oss)) = config.get::<Value>("oss")
            && !oss.contains_key("prefix")
            && !oss.contains_key("path_prefix")
        {
            builder = builder.set_default("oss.prefix", "tmp")?;
        }

        builder
            .add_source(config)
            .build()
            .map_err(sanitize_config_error)?
            .try_deserialize::<Self>()
            .map_err(sanitize_config_error)?
            .validate()
    }

    /// Load independently of global environment mutation, so tests and embedded callers can
    /// supply an isolated directory and environment. Relative path defaults still use cwd.
    pub fn load_from(
        directory: impl AsRef<Path>,
        environment: impl IntoIterator<Item = (String, String)>,
    ) -> Result<Self> {
        let directory = directory.as_ref();
        let mut toml = Map::new();
        for filename in TOML_FILES {
            let mut source = read_toml(&directory.join(filename))?;
            normalize_source(&mut source);
            // Pydantic's TOML reader uses dict.update: later top-level tables replace earlier ones.
            toml.extend(source);
        }

        let mut dotenv = BTreeMap::new();
        for filename in DOTENV_FILES {
            let path = directory.join(filename);
            let entries = match dotenvy::from_path_iter(&path) {
                Ok(entries) => entries,
                Err(dotenvy::Error::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                    continue;
                }
                Err(_) => return Err(anyhow!("failed to read dotenv file {}", path.display())),
            };
            for entry in entries {
                let (name, value) =
                    entry.map_err(|_| anyhow!("invalid dotenv file {}", path.display()))?;
                dotenv.insert(name.to_ascii_lowercase(), value);
            }
        }

        let dotenv = environment_source(dotenv)?;
        let environment = environment_source(environment)?;
        let extra = read_toml(&directory.join("config/extra.toml"))?;
        let config = Config::builder()
            .add_source(json_source(Value::Object(toml))?)
            .add_source(json_source(Value::Object(dotenv))?)
            .add_source(json_source(Value::Object(environment))?)
            .add_source(json_source(serde_json::json!({ "extra": extra }))?)
            .build()
            .map_err(sanitize_config_error)?;
        Self::from_config(config)
    }
}

fn read_toml(path: &Path) -> Result<Map<String, Value>> {
    Config::builder()
        .add_source(File::from(path).format(FileFormat::Toml).required(false))
        .build()
        .map_err(sanitize_config_error)?
        .try_deserialize()
        .map_err(sanitize_config_error)
}

fn json_source(value: Value) -> Result<Config> {
    Config::try_from(&value).map_err(sanitize_config_error)
}

fn normalize_source(source: &mut Map<String, Value>) {
    // ExtraSettings deliberately has its own TOML-only source.
    source.remove("extra");
    if let Some(app) = source.get_mut("app").and_then(Value::as_object_mut)
        && let Some(repo_type) = app.remove("repo_type")
    {
        source.entry("repo_type").or_insert(repo_type);
    }
    for (section, aliases) in [
        ("postgres", &[("database", "db")][..]),
        ("oss", &[("path_prefix", "prefix")][..]),
        (
            "providers",
            &[
                ("qwen", "dashscope"),
                ("ark", "volcengine"),
                ("gemini", "google"),
            ][..],
        ),
    ] {
        if let Some(table) = source.get_mut(section).and_then(Value::as_object_mut) {
            for &(alias, canonical) in aliases {
                if let Some(value) = table.remove(alias) {
                    table.entry(canonical).or_insert(value);
                }
            }
        }
    }
}

fn environment_source(
    entries: impl IntoIterator<Item = (String, String)>,
) -> Result<Map<String, Value>> {
    let entries: BTreeMap<_, _> = entries
        .into_iter()
        .map(|(key, value)| (key.to_ascii_lowercase(), value))
        .collect();
    let mut source = Map::new();
    // Whole JSON objects are the base; more specific nested variables override them.
    let mut nested = Vec::new();
    for (name, value) in &entries {
        if let Some(path) = environment_path(name) {
            if path.len() == 1 {
                source.insert(path[0].clone(), environment_value(&path, value)?);
            } else {
                nested.push((path, value));
            }
        }
    }
    nested.sort_by_key(|(path, _)| path.len());
    for (path, value) in nested {
        insert_path(&mut source, &path, environment_value(&path, value)?);
    }
    // API_PORT is the previous Rust CLI spelling. Explicit app.port in this source wins.
    if let Some(port) = entries.get("api_port") {
        let app = source
            .entry("app")
            .or_insert_with(|| Value::Object(Map::new()));
        if let Some(app) = app.as_object_mut() {
            app.entry("port")
                .or_insert_with(|| Value::String(port.clone()));
        }
    }
    normalize_source(&mut source);
    Ok(source)
}

fn environment_path(name: &str) -> Option<Vec<String>> {
    if ROOT_FIELDS.contains(&name) {
        return Some(vec![name.into()]);
    }
    if name.contains("__") {
        let path: Vec<_> = name.split("__").map(str::to_owned).collect();
        return (ROOT_FIELDS.contains(&path[0].as_str())
            && path.iter().all(|part| !part.is_empty()))
        .then_some(path);
    }
    // Preserve underscores inside field names, including request_context and api_prefix.
    ROOT_FIELDS.iter().find_map(|root| {
        name.strip_prefix(root)
            .and_then(|suffix| suffix.strip_prefix('_'))
            .filter(|suffix| !suffix.is_empty())
            .map(|suffix| vec![(*root).into(), suffix.into()])
    })
}

fn environment_value(path: &[String], value: &str) -> Result<Value> {
    let names: Vec<_> = path.iter().map(String::as_str).collect();
    let structured = matches!(
        names.as_slice(),
        ["admin_users"
            | "app"
            | "agent"
            | "auth"
            | "request_context"
            | "otel"
            | "oss"
            | "nacos"
            | "redis"
            | "postgres"
            | "providers"
            | "tools",]
            | [
                "auth",
                "providers" | "google" | "dingtalk" | "phone" | "password" | "header",
            ]
            | ["auth", "header", "keys"]
            | ["redis", "session_principal_keys" | "sentinel_nodes"]
            | ["providers", _]
            | ["providers", _, "models"]
            | ["tools", ..]
    );
    let nullable = matches!(
        names.as_slice(),
        ["oss" | "nacos" | "redis" | "tools"] | ["providers", _]
    );
    let text = value.trim();
    if nullable && text == "null" {
        return Ok(Value::Null);
    }
    let ipv6_nodes = matches!(names.as_slice(), ["redis", "sentinel_nodes"])
        && text
            .strip_prefix('[')
            .and_then(|value| value.split_once(']'))
            .is_some_and(|(host, _)| host.parse::<std::net::Ipv6Addr>().is_ok());
    if structured && (text.starts_with('{') || (text.starts_with('[') && !ipv6_nodes)) {
        return serde_json::from_str(text)
            .map_err(|_| anyhow!("invalid JSON configuration for key `{}`", path.join(".")));
    }
    // Let config's target-aware deserializer parse bool/numeric fields. In particular,
    // numeric-looking passwords, empty strings and literal "null" secrets stay unchanged.
    Ok(Value::String(value.into()))
}

fn insert_path(source: &mut Map<String, Value>, path: &[String], value: Value) {
    if path.len() == 1 {
        merge_value(source.entry(path[0].clone()).or_insert(Value::Null), value);
        return;
    }
    let nested = source
        .entry(path[0].clone())
        .or_insert_with(|| Value::Object(Map::new()));
    if !nested.is_object() {
        *nested = Value::Object(Map::new());
    }
    if let Some(nested) = nested.as_object_mut() {
        insert_path(nested, &path[1..], value);
    }
}

fn merge_value(target: &mut Value, value: Value) {
    match (target, value) {
        (Value::Object(target), Value::Object(source)) => {
            for (key, value) in source {
                merge_value(target.entry(key).or_insert(Value::Null), value);
            }
        }
        (target, value) => *target = value,
    }
}

/// Config's standard errors can include the offending value or a whole TOML line.
/// Keep the field path and expected type, but never attach the original error as a cause.
fn sanitize_config_error(error: ConfigError) -> anyhow::Error {
    match error {
        ConfigError::NotFound(key) => anyhow!("missing configuration field `{key}`"),
        ConfigError::Type { expected, key, .. } => match key {
            Some(key) => anyhow!("invalid configuration for key `{key}`: expected {expected}"),
            None => anyhow!("invalid configuration: expected {expected}"),
        },
        ConfigError::At { key: Some(key), .. } => {
            anyhow!("invalid configuration for key `{key}`")
        }
        ConfigError::FileParse { uri: Some(uri), .. } => {
            anyhow!("failed to parse configuration file {uri}")
        }
        _ => anyhow!("invalid configuration"),
    }
}
