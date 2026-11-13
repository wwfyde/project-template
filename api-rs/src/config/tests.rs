use super::*;
use config::Config;
use serde_json::json;
use std::path::Path;

fn database() -> Value {
    json!({"host": "localhost", "port": 5432, "username": "api", "password": "test-secret", "db": "api"})
}

fn parse(mut input: Value) -> Result<Settings> {
    input
        .as_object_mut()
        .unwrap()
        .entry("postgres")
        .or_insert_with(database);
    Settings::from_config(Config::try_from(&input)?)
}

struct ConfigDirectory(PathBuf);

impl ConfigDirectory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!("api-rs-config-{}", uuid::Uuid::now_v7()));
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn write(&self, name: &str, contents: &str) {
        let path = self.0.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, contents).unwrap();
    }

    fn load(&self, environment: &[(&str, &str)]) -> Result<Settings> {
        Settings::load_from(
            &self.0,
            environment
                .iter()
                .map(|(key, value)| (key.to_string(), value.to_string())),
        )
    }

    fn write_database(&self) {
        self.write("config.toml", "[postgres]\nhost = 'localhost'\nport = 5432\nusername = 'api'\npassword = 'test-secret'\ndb = 'api'\n");
    }
}

impl Drop for ConfigDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn omitted_fields_use_python_defaults_without_inventing_required_credentials() {
    let settings = parse(json!({})).unwrap();
    assert_eq!(settings.project_name, "Api");
    assert_eq!(settings.repo_type, RepoType::Memory);
    assert_eq!(settings.profile, Profile::Web);
    assert!(settings.admin_users.is_empty());
    assert_eq!(settings.app.name, "api");
    assert_eq!(settings.app.env, AppEnv::Dev);
    assert!(settings.app.debug);
    assert_eq!(settings.app.port, 8000);
    assert_eq!(settings.app.log_level, LogLevel::Info);
    assert_eq!(settings.httpx_timeout, 60);
    assert_eq!(settings.wait_max_seconds, 120);
    assert_eq!(settings.postgres.pool_size, 30);
    assert_eq!(settings.project_dir, Path::new(env!("CARGO_MANIFEST_DIR")));
    let cwd = std::env::current_dir().unwrap();
    assert_eq!(settings.base_dir, cwd);
    assert_eq!(settings.data_dir, cwd.join("data"));
    assert_eq!(settings.temp_dir, cwd.join("temp"));
    assert_eq!(settings.static_dir, cwd.join("web/dist"));
    assert!(settings.oss.is_none() && settings.nacos.is_none());
    assert!(settings.api_prefix.is_none() && settings.proxy_url.is_none());
    assert!(settings.tools.is_none());
    assert!(settings.providers.openai.is_none());
    assert!(settings.providers.google.is_none());
    assert!(settings.extra.a.is_none());
    let redis = settings.redis.as_ref().unwrap();
    assert_eq!(redis.session_cookie_name, "project_template_session");
    assert!(redis.session_fail_closed);
    assert_eq!(settings.redis_dsn().unwrap(), "redis://localhost:6379/0");
    assert!(settings.app.runtime_auth().is_err());
    assert!(Settings::from_config(Config::default()).is_err());
    for field in ["host", "port", "username", "password", "db"] {
        let mut postgres = database();
        postgres.as_object_mut().unwrap().remove(field);
        assert!(
            parse(json!({"postgres": postgres})).is_err(),
            "missing {field}"
        );
    }
}

#[test]
fn null_is_distinct_from_omission_and_partial_objects_keep_defaults() {
    let settings =
        parse(json!({"redis": null, "app": {"debug": false}, "base_dir": "/override"})).unwrap();
    assert!(settings.redis.is_none());
    assert_eq!(settings.redis_dsn().unwrap(), "");
    assert!(!settings.app.debug);
    assert_eq!(settings.app.port, 8000);
    assert_eq!(settings.base_dir, Path::new("/override"));
    assert_eq!(
        settings.data_dir,
        std::env::current_dir().unwrap().join("data")
    );
    for value in [
        json!({"app": null}),
        json!({"postgres": null}),
        json!({"extra": {"a": null}}),
    ] {
        assert!(parse(value).is_err());
    }
    assert!(
        parse(json!({"extra": {"a": ""}}))
            .unwrap()
            .extra
            .a
            .is_some()
    );
}

#[test]
fn literals_reject_invalid_values_and_accept_every_python_variant() {
    for repo in ["memory", "postgres", "mongodb", "mysql", "redis"] {
        parse(json!({"repo_type": repo})).unwrap();
    }
    for profile in ["web", "cli", "desktop", "app"] {
        parse(json!({"profile": profile})).unwrap();
    }
    for environment in ["dev", "prod", "local"] {
        parse(json!({"app": {"env": environment}})).unwrap();
    }
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] {
        parse(json!({"app": {"log_level": level}})).unwrap();
    }
    for input in [
        json!({"repo_type": "in-memory"}),
        json!({"profile": "server"}),
        json!({"app": {"env": "staging"}}),
        json!({"app": {"log_level": "info"}}),
        json!({"redis": {"session_cookie_same_site": "invalid"}}),
    ] {
        assert!(parse(input).is_err());
    }
}

#[test]
fn providers_preserve_aliases_optional_values_and_extension_fields() {
    let provider =
        json!({"base_url": "https://example.test/v1", "api_key": "key", "model": "test-model"});
    let settings = parse(json!({"providers": {
        "qwen": provider, "ark": provider,
        "gemini": {"base_url": "https://google.example/v1", "api_key": "key", "model": "gemini",
                   "vertex_api_key": null, "custom_option": {"nested": [1, true]}}
    }, "oss": {"bucket_name": "bucket", "access_key_id": "id", "access_key_secret": "secret", "path_prefix": "images"}})).unwrap();
    assert_eq!(settings.providers.dashscope.unwrap().model, "test-model");
    assert_eq!(settings.providers.volcengine.unwrap().model, "test-model");
    let google = settings.providers.google.unwrap();
    assert!(!google.use_vertexai);
    assert!(google.vertex_api_key.is_none());
    assert!(google.image_model.is_none());
    assert!(google.max_tokens.is_none() && google.temperature.is_none());
    assert!(matches!(&google.models, Models::Names(models) if models.is_empty()));
    assert_eq!(google.extra["custom_option"], json!({"nested": [1, true]}));
    assert_eq!(settings.oss.unwrap().prefix, "images");
    for field in ["base_url", "api_key", "model"] {
        let mut incomplete = provider.clone();
        incomplete.as_object_mut().unwrap().remove(field);
        assert!(parse(json!({"providers": {"openai": incomplete}})).is_err());
    }
}

#[test]
fn model_union_requires_homogeneous_lists_and_literal_object_type() {
    let descriptor =
        json!({"id": "model-1", "created": 1700000000, "object": "model", "owned_by": "test"});
    let provider = |models| json!({"providers": {"openai": {"base_url": "https://example.test", "api_key": "key", "model": "model-1", "models": models}}});
    let names = parse(provider(json!(["model-1", "model-2"]))).unwrap();
    assert!(
        matches!(names.providers.openai.unwrap().models, Models::Names(items) if items.len() == 2)
    );
    let models = parse(provider(json!([descriptor]))).unwrap();
    assert!(
        matches!(models.providers.openai.unwrap().models, Models::Descriptions(items) if items[0].object == ModelObject::Model)
    );
    assert!(parse(provider(json!(["model-1", descriptor]))).is_err());
    let mut invalid = descriptor;
    invalid["object"] = json!("completion");
    assert!(parse(provider(json!([invalid]))).is_err());
}

#[test]
fn connection_urls_encode_secrets_and_support_ipv6() {
    let mut settings = parse(json!({})).unwrap();
    settings.postgres.username = "user@tenant".into();
    settings.postgres.password = "p@ss:/?#%".into();
    settings.postgres.db = "db/name?#".into();
    assert_eq!(
        settings.postgres_dsn().unwrap(),
        "postgresql://user%40tenant:p%40ss%3A%2F%3F%23%25@localhost:5432/db%2Fname%3F%23"
    );
    settings.postgres.host = "::1".into();
    assert!(settings.postgres_dsn().unwrap().contains("@[::1]:5432/"));
    let secret = SecretString::from("never-print-this-key");
    assert!(!format!("{secret:?}").contains(secret.expose_secret()));
    assert_eq!(serde_json::to_string(&secret).unwrap(), "\"**********\"");
}

#[test]
fn example_and_legacy_rust_authentication_configuration_are_valid() {
    let settings = Settings::from_config(
        Config::builder()
            .add_source(config::File::from_str(
                include_str!("../../config.example.toml"),
                config::FileFormat::Toml,
            ))
            .build()
            .unwrap(),
    )
    .unwrap();
    settings.app.runtime_auth().unwrap();
    for days in [0, -1, i64::MAX] {
        let mut app = settings.app.clone();
        app.access_token_expire_days = Some(days);
        assert!(app.runtime_auth().is_err());
    }
    let mut app = settings.app.clone();
    app.api_key = Some(" ".into());
    assert!(app.runtime_auth().is_err());
    let mut app = settings.app;
    app.jwt_secret = None;
    assert!(app.runtime_auth().is_err());
}

#[test]
fn environment_only_configuration_supports_python_names_and_json() {
    let directory = ConfigDirectory::new();
    let settings = directory
        .load(&[
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PORT", "5432"),
            ("POSTGRES_USERNAME", "api"),
            ("POSTGRES_PASSWORD", "001234"),
            ("POSTGRES_DATABASE", "api"),
            ("POSTGRES_POOL_SIZE", "15"),
            ("APP_ENV", "prod"),
            ("APP_DEBUG", "false"),
            ("AUTH_FRONTEND_URL", "https://app.example.test"),
            (
                "AUTH_PASSWORD",
                "{\"enabled\":true,\"rate_limit_attempts\":7}",
            ),
            ("REQUEST_CONTEXT_ACCEPT_REQUEST_ID", "false"),
            ("ADMIN_USERS", "[\"admin\"]"),
            (
                "PROVIDERS_OPENAI",
                "{\"base_url\":\"https://example.test\",\"api_key\":\"key\",\"model\":\"m\"}",
            ),
            ("REDIS_SENTINEL", "true"),
            ("REDIS_SENTINEL_NODES", "redis-a,redis-b:26380"),
        ])
        .unwrap();
    assert_eq!(settings.postgres.host, "postgres");
    assert_eq!(settings.postgres.password.expose_secret(), "001234");
    assert_eq!(settings.postgres.pool_size, 15);
    assert_eq!(settings.app.env, AppEnv::Prod);
    assert!(!settings.app.debug);
    assert!(settings.auth.password.enabled);
    assert_eq!(settings.auth.password.rate_limit_attempts, 7);
    assert!(!settings.request_context.accept_request_id);
    assert_eq!(settings.admin_users, ["admin"]);
    assert_eq!(settings.providers.openai.unwrap().model, "m");
    assert_eq!(
        settings.redis.unwrap().sentinel_addresses().unwrap(),
        [("redis-a".into(), 26379), ("redis-b".into(), 26380)]
    );
}

#[test]
fn loader_preserves_source_order_shallow_toml_tables_and_separate_extra() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    directory.write(
        "config.dev.toml",
        "project_name = 'dev'\n[app]\nname = 'from-dev'\nport = 9000\n[extra]\na = 'ignored'\n",
    );
    directory.write(
        "config.prod.local.toml",
        "project_name = 'last-toml'\n[app]\ndebug = false\n",
    );
    directory.write(".env", "APP_PORT=9100\nPROJECT_NAME=first-dotenv\n");
    directory.write(
        ".env.prod.local",
        "APP_PORT=9200\nPROJECT_NAME=last-dotenv\n",
    );
    directory.write("config/extra.toml", "a = 'only-extra-file'\n");
    let settings = directory
        .load(&[
            ("APP_ENV", "dev"),
            ("PROJECT_NAME", "process"),
            ("EXTRA_A", "ignored-process"),
        ])
        .unwrap();
    assert_eq!(settings.project_name, "process");
    assert_eq!(settings.app.name, "api"); // later TOML table replaces all of app
    assert!(!settings.app.debug); // prod.local participates even when APP_ENV=dev
    assert_eq!(settings.app.port, 9200);
    assert_eq!(settings.extra.a.as_deref(), Some("only-extra-file"));
    assert_eq!(directory.load(&[]).unwrap().project_name, "last-dotenv");
    assert_eq!(
        directory.load(&[("APP_PORT", "9300")]).unwrap().app.port,
        9300
    );
}

#[test]
fn aliases_and_legacy_double_underscore_overrides_merge_without_duplicates() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    directory.write("config.local.toml", "[providers.ark]\nbase_url = 'https://example.test'\napi_key = 'key'\nmodel = 'original'\n[app]\nrepo_type = 'postgres'\n");
    let settings = directory
        .load(&[
            ("POSTGRES__DATABASE", "overridden"),
            ("PROVIDERS__VOLCENGINE__MODEL", "updated"),
        ])
        .unwrap();
    assert_eq!(settings.postgres.db, "overridden");
    assert_eq!(settings.repo_type, RepoType::Postgres);
    assert_eq!(settings.providers.volcengine.unwrap().model, "updated");
    let settings = directory
        .load(&[
            ("POSTGRES_DATABASE", "alias"),
            ("POSTGRES_DB", "canonical"),
            ("REPO_TYPE", "memory"),
        ])
        .unwrap();
    assert_eq!(settings.postgres.db, "canonical");
    assert_eq!(settings.repo_type, RepoType::Memory);
}

#[test]
fn environment_objects_merge_with_nested_keys_and_null_disables_redis() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    let settings = directory
        .load(&[
            ("POSTGRES", "{\"pool_size\":12,\"password\":\"original\"}"),
            ("POSTGRES_PASSWORD", "null"),
            ("REDIS", "null"),
            ("APP", "{\"port\":8100,\"debug\":false}"),
            ("APP_PORT", "8200"),
        ])
        .unwrap();
    assert_eq!(settings.postgres.pool_size, 12);
    assert_eq!(settings.postgres.password.expose_secret(), "null");
    assert!(settings.redis.is_none());
    assert!(!settings.app.debug);
    assert_eq!(settings.app.port, 8200);
    assert!(
        directory
            .load(&[("AUTH_GOOGLE_CLIENT_ID", "does-not-expand-twice")])
            .is_err()
    );
}

#[test]
fn legacy_api_port_and_secret_error_handling() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    directory.write(".env", "API_PORT=8123\n");
    assert_eq!(directory.load(&[]).unwrap().app.port, 8123);
    assert_eq!(
        directory
            .load(&[("API_PORT", "8234"), ("APP_PORT", "8345")])
            .unwrap()
            .app
            .port,
        8345
    );
    let secret = "secret-should-never-be-printed";
    for key in ["POSTGRES_PORT", "PROVIDERS_OPENAI", "AUTH_HEADER"] {
        let error = directory.load(&[(key, secret)]).err().unwrap();
        assert!(!format!("{error:#}").contains(secret));
    }
}

#[test]
fn google_flattened_provider_accepts_typed_environment_overrides() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    let settings = directory
        .load(&[
            ("PROVIDERS__GOOGLE__BASE_URL", "https://example.test"),
            ("PROVIDERS__GOOGLE__API_KEY", "001234"),
            ("PROVIDERS__GOOGLE__MODEL", "model"),
            ("PROVIDERS__GOOGLE__MAX_TOKENS", "42"),
            ("PROVIDERS__GOOGLE__TEMPERATURE", "0.5"),
            ("PROVIDERS__GOOGLE__USE_VERTEXAI", "true"),
        ])
        .unwrap();
    let google = settings.providers.google.unwrap();
    assert_eq!(google.api_key.expose_secret(), "001234");
    assert_eq!(google.max_tokens, Some(42));
    assert_eq!(google.temperature, Some(0.5));
    assert!(google.use_vertexai);
}

#[test]
fn nested_json_environment_values_merge_with_whole_objects() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    let settings = directory
        .load(&[
            (
                "PROVIDERS",
                r#"{"openai":{"base_url":"https://example.test","api_key":"key","model":"old"}}"#,
            ),
            ("PROVIDERS_OPENAI", r#"{"model":"new"}"#),
            (
                "AUTH",
                r#"{"password":{"enabled":true,"rate_limit_attempts":7}}"#,
            ),
            ("AUTH_PASSWORD", r#"{"enabled":false}"#),
        ])
        .unwrap();
    let provider = settings.providers.openai.unwrap();
    assert_eq!(provider.base_url, "https://example.test");
    assert_eq!(provider.model, "new");
    assert!(!settings.auth.password.enabled);
    assert_eq!(settings.auth.password.rate_limit_attempts, 7);
}

#[test]
fn set_defaults_are_overridden_by_sources_and_invalid_values_still_fail() {
    let directory = ConfigDirectory::new();
    directory.write_database();
    directory.write(
        "config.dev.toml",
        "httpx_timeout = 15\nwait_max_seconds = 45\n",
    );
    let settings = directory.load(&[]).unwrap();
    assert_eq!(settings.httpx_timeout, 15);
    assert_eq!(settings.wait_max_seconds, 45);
    let settings = directory
        .load(&[("HTTPX_TIMEOUT", "30"), ("WAIT_MAX_SECONDS", "90")])
        .unwrap();
    assert_eq!(settings.httpx_timeout, 30);
    assert_eq!(settings.wait_max_seconds, 90);
    assert!(directory.load(&[("HTTPX_TIMEOUT", "invalid")]).is_err());
}

#[test]
fn oss_prefix_default_preserves_optional_section_and_alias_semantics() {
    assert!(parse(json!({})).unwrap().oss.is_none());
    assert!(parse(json!({"oss": null})).unwrap().oss.is_none());
    let mut oss =
        json!({"bucket_name": "bucket", "access_key_id": "id", "access_key_secret": "secret"});
    assert_eq!(
        parse(json!({"oss": oss})).unwrap().oss.unwrap().prefix,
        "tmp"
    );
    oss["path_prefix"] = json!("uploads");
    assert_eq!(
        parse(json!({"oss": oss})).unwrap().oss.unwrap().prefix,
        "uploads"
    );
    oss.as_object_mut().unwrap().remove("path_prefix");
    oss["prefix"] = json!("");
    assert_eq!(parse(json!({"oss": oss})).unwrap().oss.unwrap().prefix, "");
}
