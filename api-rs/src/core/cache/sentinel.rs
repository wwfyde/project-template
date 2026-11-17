use std::sync::Arc;
use std::time::Duration;

use futures_util::stream::{FuturesUnordered, StreamExt};
use redis::aio::{ConnectionLike, MultiplexedConnection};
use redis::sentinel::SentinelClient;
use redis::{AsyncConnectionConfig, Cmd, Pipeline, RedisError, RedisFuture, RedisResult, Value};
use tokio::sync::Mutex;

use super::options;
use crate::config::RedisConfig;

/// Sentinel 重新发现主节点；不能把首次发现的固定地址交给 ConnectionManager 后就不再发现。
#[derive(Clone)]
pub struct SentinelConnection {
    inner: Arc<Mutex<SentinelState>>,
    db: i64,
}

struct SentinelState {
    clients: Vec<SentinelClient>,
    connection: Option<MultiplexedConnection>,
    generation: u64,
    config: AsyncConnectionConfig,
    discovery_timeout: Duration,
}

impl SentinelConnection {
    pub async fn connect(
        clients: Vec<SentinelClient>,
        config: &RedisConfig,
    ) -> anyhow::Result<Self> {
        let connection_timeout = options::connection_timeout(config)?;
        let connection = Self {
            inner: Arc::new(Mutex::new(SentinelState {
                clients,
                connection: None,
                generation: 0,
                config: AsyncConnectionConfig::new()
                    .set_connection_timeout(Some(connection_timeout))
                    .set_response_timeout(Some(options::response_timeout(config)?)),
                discovery_timeout: connection_timeout,
            })),
            db: i64::try_from(config.db)?,
        };
        connection.connection().await?;
        Ok(connection)
    }

    async fn connection(&self) -> RedisResult<(u64, MultiplexedConnection)> {
        let mut state = self.inner.lock().await;
        if let Some(connection) = &state.connection {
            return Ok((state.generation, connection.clone()));
        }

        let config = state.config.clone();
        let discovery_timeout = state.discovery_timeout;
        for attempt in 0..=options::RECONNECT_RETRIES {
            let result = discover(&mut state.clients, &config, discovery_timeout).await;
            match result {
                Ok(connection) => {
                    state.generation = state.generation.wrapping_add(1);
                    state.connection = Some(connection.clone());
                    return Ok((state.generation, connection));
                }
                Err(error) if attempt == options::RECONNECT_RETRIES => return Err(error),
                Err(_) => {
                    let delay =
                        Duration::from_millis(100 * 2u64.pow(attempt)).min(Duration::from_secs(2));
                    tokio::time::sleep(delay).await;
                }
            }
        }
        unreachable!("the final discovery attempt returns its result")
    }

    async fn invalidate_if_needed(&self, generation: u64, needs_rediscovery: bool) {
        if needs_rediscovery {
            let mut state = self.inner.lock().await;
            if state.generation == generation {
                state.connection = None;
            }
        }
    }
}

async fn discover(
    clients: &mut [SentinelClient],
    config: &AsyncConnectionConfig,
    timeout: Duration,
) -> RedisResult<MultiplexedConnection> {
    // 每个 seed 独立发现并取首个成功结果，首节点黑洞不能阻塞其它健康 Sentinel。
    // 超时覆盖 Sentinel 查询、ROLE 校验及最终数据连接。
    let mut attempts: FuturesUnordered<_> = clients
        .iter_mut()
        .map(|client| {
            tokio::time::timeout(timeout, client.get_async_connection_with_config(config))
        })
        .collect();
    let mut last_error = std::io::Error::new(
        std::io::ErrorKind::TimedOut,
        "Redis Sentinel discovery timed out",
    )
    .into();
    while let Some(result) = attempts.next().await {
        match result {
            Ok(Ok(connection)) => return Ok(connection),
            Ok(Err(error)) => last_error = error,
            Err(_) => {}
        }
    }
    Err(last_error)
}

fn error_requires_rediscovery(error: &RedisError) -> bool {
    error.is_io_error()
        || matches!(error.code(), Some("READONLY" | "MASTERDOWN"))
        || error.clone().into_server_errors().is_some_and(|errors| {
            errors
                .iter()
                .any(|(_, error)| matches!(error.code(), "READONLY" | "MASTERDOWN"))
        })
}

// redis-rs v2 在 ConnectionLike 层将服务端错误保留为 Value；query_async 才会转换成 Err。
fn value_requires_rediscovery(value: &Value) -> bool {
    match value {
        Value::ServerError(error) => matches!(error.code(), "READONLY" | "MASTERDOWN"),
        Value::Array(values) | Value::Set(values) | Value::Push { data: values, .. } => {
            values.iter().any(value_requires_rediscovery)
        }
        Value::Attribute { data, attributes } => {
            value_requires_rediscovery(data)
                || attributes.iter().any(|(key, value)| {
                    value_requires_rediscovery(key) || value_requires_rediscovery(value)
                })
        }
        Value::Map(values) => values.iter().any(|(key, value)| {
            value_requires_rediscovery(key) || value_requires_rediscovery(value)
        }),
        _ => false,
    }
}

impl ConnectionLike for SentinelConnection {
    fn req_packed_command<'a>(&'a mut self, cmd: &'a Cmd) -> RedisFuture<'a, Value> {
        Box::pin(async move {
            let (generation, mut connection) = self.connection().await?;
            // 不持锁执行命令；连接可并发复用。失败命令可能已执行，不自动重放写操作。
            let result = connection.req_packed_command(cmd).await;
            let needs_rediscovery = result
                .as_ref()
                .map_or_else(error_requires_rediscovery, value_requires_rediscovery);
            self.invalidate_if_needed(generation, needs_rediscovery)
                .await;
            result
        })
    }

    fn req_packed_commands<'a>(
        &'a mut self,
        pipeline: &'a Pipeline,
        offset: usize,
        count: usize,
    ) -> RedisFuture<'a, Vec<Value>> {
        Box::pin(async move {
            let (generation, mut connection) = self.connection().await?;
            let result = connection
                .req_packed_commands(pipeline, offset, count)
                .await;
            let needs_rediscovery = result
                .as_ref()
                .map_or_else(error_requires_rediscovery, |values| {
                    values.iter().any(value_requires_rediscovery)
                });
            self.invalidate_if_needed(generation, needs_rediscovery)
                .await;
            result
        })
    }

    fn get_db(&self) -> i64 {
        self.db
    }
}

#[cfg(test)]
mod tests;
