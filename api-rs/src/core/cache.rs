//! 可克隆的异步 Redis 长连接；克隆共享连接，不需要外层 Mutex 或连接池。

mod options;
mod sentinel;

use anyhow::{Context, Result, ensure};
use redis::aio::{ConnectionLike, ConnectionManager};
use redis::{Cmd, Pipeline, RedisFuture, Value};

use crate::config::RedisConfig;
use sentinel::SentinelConnection;

/// 单机和哨兵共享同一业务接口；连接方式只在应用初始化时选择。
/// 克隆后直接使用 `redis::AsyncCommands`，不暴露底层连接类型。
#[derive(Clone)]
pub struct CacheConnection {
    inner: Connection,
}

#[derive(Clone)]
enum Connection {
    Standalone(ConnectionManager),
    Sentinel(SentinelConnection),
}

impl CacheConnection {
    /// 创建单机连接，断线由 ConnectionManager 自动恢复。
    pub async fn standalone(config: &RedisConfig) -> Result<Self> {
        ensure!(
            !config.sentinel,
            "standalone cache requires redis.sentinel=false"
        );
        let certificates = options::prepare(config).await?;
        let client = options::standalone_client(config, certificates)?;
        let connection =
            ConnectionManager::new_with_config(client, options::manager_config(config)?)
                .await
                .context("failed to connect to Redis")?;
        Ok(Self {
            inner: Connection::Standalone(connection),
        })
    }

    /// 连接哨兵发现的主节点，故障后重新发现主节点。
    pub async fn sentinel(config: &RedisConfig) -> Result<Self> {
        ensure!(
            config.sentinel,
            "sentinel cache requires redis.sentinel=true"
        );
        let certificates = options::prepare(config).await?;
        let clients = options::sentinel_clients(config, certificates)?;
        let connection = SentinelConnection::connect(clients, config)
            .await
            .context("failed to discover and connect to Redis primary")?;
        Ok(Self {
            inner: Connection::Sentinel(connection),
        })
    }
}

impl ConnectionLike for CacheConnection {
    fn req_packed_command<'a>(&'a mut self, cmd: &'a Cmd) -> RedisFuture<'a, Value> {
        match &mut self.inner {
            Connection::Standalone(connection) => connection.req_packed_command(cmd),
            Connection::Sentinel(connection) => connection.req_packed_command(cmd),
        }
    }

    fn req_packed_commands<'a>(
        &'a mut self,
        pipeline: &'a Pipeline,
        offset: usize,
        count: usize,
    ) -> RedisFuture<'a, Vec<Value>> {
        match &mut self.inner {
            Connection::Standalone(connection) => {
                connection.req_packed_commands(pipeline, offset, count)
            }
            Connection::Sentinel(connection) => {
                connection.req_packed_commands(pipeline, offset, count)
            }
        }
    }

    fn get_db(&self) -> i64 {
        match &self.inner {
            Connection::Standalone(connection) => connection.get_db(),
            Connection::Sentinel(connection) => connection.get_db(),
        }
    }
}

#[cfg(test)]
mod tests;
