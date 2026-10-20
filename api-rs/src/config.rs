use anyhow::{Context, Result, ensure};
use config::{Case, Config};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use serde::Deserialize;
use url::Url;

/// Postgres 配置。凭据通过 URL 编码后传给 SeaORM。
#[derive(Clone, Deserialize)]
pub struct PostgresConfig {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub password: String,
    pub database: String,
}

impl PostgresConfig {
    pub fn connection_url(&self) -> Result<Url> {
        let mut url = Url::parse("postgresql://localhost")?;
        url.set_host(Some(&self.host))
            .context("invalid postgres host")?;
        url.set_port(Some(self.port))
            .map_err(|_| anyhow::anyhow!("invalid postgres port"))?;
        url.set_username(&utf8_percent_encode(&self.username, NON_ALPHANUMERIC).to_string())
            .map_err(|_| anyhow::anyhow!("invalid postgres username"))?;
        url.set_password(Some(
            &utf8_percent_encode(&self.password, NON_ALPHANUMERIC).to_string(),
        ))
        .map_err(|_| anyhow::anyhow!("invalid postgres password"))?;
        url.path_segments_mut()
            .map_err(|_| anyhow::anyhow!("invalid postgres URL"))?
            .clear()
            .push(&self.database);
        Ok(url)
    }
}

#[derive(Clone, Deserialize)]
pub struct App {
    pub api_key: String,
    pub jwt_secret: String,
    pub access_token_expire_days: i64,
}

#[derive(Clone, Deserialize)]
pub struct Settings {
    pub app: App,
    pub postgres: PostgresConfig,
}

impl Settings {
    fn validate(self) -> Result<Self> {
        ensure!(
            !self.app.api_key.trim().is_empty(),
            "app.api_key is required"
        );
        ensure!(
            !self.app.jwt_secret.trim().is_empty(),
            "app.jwt_secret is required"
        );
        ensure!(
            self.app.access_token_expire_days > 0
                && chrono::Duration::try_days(self.app.access_token_expire_days)
                    .and_then(|duration| chrono::Utc::now().checked_add_signed(duration))
                    .is_some(),
            "app.access_token_expire_days must be a positive, representable duration"
        );
        ensure!(self.postgres.port > 0, "postgres.port must be nonzero");
        ensure!(
            !self.postgres.database.is_empty(),
            "postgres.database is required"
        );
        self.postgres.connection_url()?;
        Ok(self)
    }
}

pub fn load_config() -> Result<Settings> {
    let mut builder =
        Config::builder().add_source(config::File::with_name("config.toml").required(false));

    // Only load the selected environment; never combine dev and prod settings.
    if let Ok(environment) = std::env::var("APP_ENV") {
        ensure!(
            !environment.is_empty()
                && environment
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'),
            "APP_ENV must contain only letters, digits, hyphens or underscores"
        );
        builder = builder.add_source(
            config::File::with_name(&format!("config.{environment}.toml")).required(false),
        );
    }

    builder
        .add_source(config::File::with_name("config.local.toml").required(false))
        .add_source(
            config::Environment::with_convert_case(Case::Snake)
                .separator("__")
                .try_parsing(true),
        )
        .build()
        .context("failed to load configuration")?
        .try_deserialize::<Settings>()
        .context("invalid configuration")?
        .validate()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> Settings {
        Config::builder()
            .add_source(config::File::from_str(
                include_str!("../config.example.toml"),
                config::FileFormat::Toml,
            ))
            .build()
            .unwrap()
            .try_deserialize()
            .unwrap()
    }

    #[test]
    fn example_configuration_is_complete() {
        settings().validate().unwrap();
    }

    #[test]
    fn connection_url_encodes_credentials_and_database() {
        let mut postgres = settings().postgres;
        postgres.username = "user@tenant".into();
        postgres.password = "p@ss:/?#%".into();
        postgres.database = "db/name?#".into();
        assert_eq!(
            postgres.connection_url().unwrap().as_str(),
            "postgresql://user%40tenant:p%40ss%3A%2F%3F%23%25@localhost:5432/db%2Fname%3F%23"
        );
    }

    #[test]
    fn rejects_missing_secrets_and_invalid_token_lifetimes() {
        let mut config = settings();
        config.app.api_key.clear();
        assert!(config.validate().is_err());
        let mut config = settings();
        config.app.jwt_secret.clear();
        assert!(config.validate().is_err());
        for days in [0, -1, i64::MAX] {
            let mut config = settings();
            config.app.access_token_expire_days = days;
            assert!(config.validate().is_err());
        }
    }
}
