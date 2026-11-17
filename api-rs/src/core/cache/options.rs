use std::time::Duration;

use anyhow::{Context, Result, ensure};
use redis::aio::ConnectionManagerConfig;
use redis::io::tcp::{TcpSettings, socket2::TcpKeepalive};
use redis::sentinel::{SentinelClient, SentinelClientBuilder, SentinelServerType};
use redis::{Client, ClientTlsConfig, ConnectionAddr, ConnectionInfo, IntoConnectionInfo};
use redis::{TlsCertificates, TlsMode};

use crate::config::RedisConfig;

pub(super) const RECONNECT_RETRIES: u32 = 6;
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(5);

pub(super) async fn prepare(config: &RedisConfig) -> Result<Option<TlsCertificates>> {
    config.validate()?;
    validate_tls(config)?;
    // SQLx 和 reqwest 同时启用 ring/aws-lc；已有 provider 时保留宿主选择。
    let _ = rustls::crypto::ring::default_provider().install_default();
    certificates(config).await
}

pub(super) fn connection_timeout(config: &RedisConfig) -> Result<Duration> {
    timeout(config.socket_connect_timeout)
}

pub(super) fn response_timeout(config: &RedisConfig) -> Result<Duration> {
    timeout(config.socket_timeout)
}

fn timeout(seconds: Option<f64>) -> Result<Duration> {
    seconds.map_or(Ok(DEFAULT_TIMEOUT), |seconds| {
        Duration::try_from_secs_f64(seconds).context("invalid Redis timeout")
    })
}

fn tcp_settings() -> TcpSettings {
    TcpSettings::default().set_keepalive(
        TcpKeepalive::new()
            .with_time(Duration::from_secs(60))
            .with_interval(Duration::from_secs(15)),
    )
}

fn validate_tls(config: &RedisConfig) -> Result<()> {
    ensure!(
        config.ssl_check_hostname,
        "Redis TLS requires ssl_check_hostname=true"
    );
    ensure!(
        config.ssl_certfile.is_some() == config.ssl_keyfile.is_some(),
        "redis.ssl_certfile and redis.ssl_keyfile must be supplied together"
    );
    Ok(())
}

async fn certificates(config: &RedisConfig) -> Result<Option<TlsCertificates>> {
    let mut certificates = TlsCertificates::new();
    if let (Some(cert), Some(key)) = (&config.ssl_certfile, &config.ssl_keyfile) {
        certificates = certificates.client_tls_config(ClientTlsConfig::new(
            tokio::fs::read(cert)
                .await
                .context("failed to read Redis TLS certificate")?,
            tokio::fs::read(key)
                .await
                .context("failed to read Redis TLS key")?,
        ));
    }
    if let Some(ca) = &config.ssl_ca_certs {
        certificates = certificates.root_cert(
            tokio::fs::read(ca)
                .await
                .context("failed to read Redis TLS CA")?,
        );
    }
    Ok((config.ssl_certfile.is_some() || config.ssl_ca_certs.is_some()).then_some(certificates))
}

fn connection_info(url: &str) -> Result<ConnectionInfo> {
    let info = url
        .into_connection_info()
        .context("invalid Redis connection URL")?;
    ensure!(
        info.redis_settings().db() >= 0,
        "Redis database must be nonnegative"
    );
    if let ConnectionAddr::TcpTls { insecure, .. } = info.addr() {
        ensure!(
            !insecure,
            "Redis TLS certificate verification must be enabled"
        );
    }
    Ok(info.set_tcp_settings(tcp_settings()))
}

pub(super) fn standalone_client(
    config: &RedisConfig,
    certificates: Option<TlsCertificates>,
) -> Result<Client> {
    let info = connection_info(&config.connection_url()?)?;
    match certificates {
        Some(certificates) => {
            ensure!(
                matches!(info.addr(), ConnectionAddr::TcpTls { .. }),
                "Redis TLS certificates require rediss or ssl=true"
            );
            Ok(Client::build_with_tls(info, certificates)?)
        }
        None => Ok(Client::open(info)?),
    }
}

pub(super) fn manager_config(config: &RedisConfig) -> Result<ConnectionManagerConfig> {
    Ok(ConnectionManagerConfig::new()
        .set_connection_timeout(Some(connection_timeout(config)?))
        .set_response_timeout(Some(response_timeout(config)?))
        .set_number_of_retries(RECONNECT_RETRIES as usize)
        .set_max_delay(Duration::from_secs(2)))
}

pub(super) fn sentinel_clients(
    config: &RedisConfig,
    certificates: Option<TlsCertificates>,
) -> Result<Vec<SentinelClient>> {
    let nodes = config
        .sentinel_addresses()?
        .into_iter()
        .map(|(host, port)| {
            if config.ssl {
                ConnectionAddr::TcpTls {
                    host,
                    port,
                    insecure: false,
                    tls_params: None,
                }
            } else {
                ConnectionAddr::Tcp(host, port)
            }
        });
    nodes
        .map(|node| sentinel_client(config, node, certificates.clone()))
        .collect()
}

fn sentinel_client(
    config: &RedisConfig,
    node: ConnectionAddr,
    certificates: Option<TlsCertificates>,
) -> Result<SentinelClient> {
    let mut builder = SentinelClientBuilder::new(
        [node],
        &config.sentinel_master_name,
        SentinelServerType::Master,
    )?
    .set_client_to_redis_db(i64::try_from(config.db).context("Redis database is out of range")?)
    .set_client_to_redis_tcp_settings(tcp_settings())
    .set_client_to_sentinel_tcp_settings(tcp_settings());
    let username = config.username.as_deref().filter(|value| !value.is_empty());
    if let Some(username) = username {
        builder = builder.set_client_to_redis_username(username);
    }
    if let Some(password) = config
        .password
        .as_ref()
        .filter(|password| !password.expose_secret().is_empty() || username.is_some())
    {
        builder = builder.set_client_to_redis_password(password.expose_secret());
    }
    let sentinel_username = config
        .sentinel_username
        .as_deref()
        .filter(|value| !value.is_empty());
    if let Some(username) = sentinel_username {
        builder = builder.set_client_to_sentinel_username(username);
    }
    if let Some(password) = config
        .sentinel_password
        .as_ref()
        .filter(|password| !password.expose_secret().is_empty() || sentinel_username.is_some())
    {
        builder = builder.set_client_to_sentinel_password(password.expose_secret());
    }
    if config.ssl {
        builder = builder
            .set_client_to_redis_tls_mode(TlsMode::Secure)
            .set_client_to_sentinel_tls_mode(TlsMode::Secure);
    }
    if let Some(certificates) = certificates {
        ensure!(
            config.ssl,
            "Redis Sentinel TLS certificates require ssl=true"
        );
        builder = builder
            .set_client_to_redis_certificates(certificates.clone())
            .set_client_to_sentinel_certificates(certificates);
    }
    Ok(builder.build()?)
}
