use super::CacheConnection;
use crate::config::RedisConfig;
use redis::{AsyncCommands, aio::MultiplexedConnection};
use std::time::Duration;
use tokio::time::{sleep, timeout};
use uuid::Uuid;

const REDIS_PASSWORD: &str = "api-rs-disposable-redis";
const SENTINEL_PASSWORD: &str = "api-rs-disposable-sentinel";

fn fixture_port(offset: u16) -> u16 {
    assert_eq!(
        std::env::var("API_RS_REDIS_TEST_DISPOSABLE").as_deref(),
        Ok("1"),
        "run api-rs/scripts/test-redis.sh to create an isolated disposable fixture"
    );
    let base: u16 = std::env::var("API_RS_REDIS_TEST_BASE_PORT")
        .expect("set API_RS_REDIS_TEST_BASE_PORT using the Redis test script")
        .parse()
        .unwrap();
    assert!((20_000..40_000).contains(&base));
    base + offset
}

fn config(port: u16) -> RedisConfig {
    RedisConfig {
        host: "127.0.0.1".into(),
        port,
        password: Some(REDIS_PASSWORD.into()),
        socket_timeout: Some(2.0),
        socket_connect_timeout: Some(2.0),
        ..RedisConfig::default()
    }
}

async fn admin(port: u16, password: &str) -> MultiplexedConnection {
    redis::Client::open(format!("redis://:{password}@127.0.0.1:{port}/0"))
        .unwrap()
        .get_multiplexed_async_connection()
        .await
        .unwrap()
}

async fn connect(config: &RedisConfig) -> anyhow::Result<CacheConnection> {
    if config.sentinel {
        CacheConnection::sentinel(config).await
    } else {
        CacheConnection::standalone(config).await
    }
}

async fn client_id(connection: &mut CacheConnection) -> i64 {
    redis::cmd("CLIENT")
        .arg("ID")
        .query_async(connection)
        .await
        .unwrap()
}

#[tokio::test]
async fn invalid_connection_url_is_rejected_before_network_access() {
    let config = RedisConfig {
        url: Some("https://localhost:6379".into()),
        ..RedisConfig::default()
    };
    assert!(connect(&config).await.is_err());
}

#[tokio::test]
#[ignore = "requires disposable Redis fixtures created by api-rs/scripts/test-redis.sh"]
async fn standalone_recovers_a_shared_connection_after_disconnect() {
    let port = fixture_port(0);
    let mut cache = connect(&config(port)).await.unwrap();
    let mut shared = cache.clone();
    let key = format!("api-rs-test:{}", Uuid::now_v7());
    cache.set_ex::<_, _, ()>(&key, "cached", 60).await.unwrap();
    assert_eq!(shared.get::<_, String>(&key).await.unwrap(), "cached");
    let ttl: i64 = shared.ttl(&key).await.unwrap();
    assert!((1..=60).contains(&ttl));

    let id: i64 = redis::cmd("CLIENT")
        .arg("ID")
        .query_async(&mut shared)
        .await
        .unwrap();
    let mut admin = admin(port, REDIS_PASSWORD).await;
    let killed: i64 = redis::cmd("CLIENT")
        .arg("KILL")
        .arg("ID")
        .arg(id)
        .query_async(&mut admin)
        .await
        .unwrap();
    assert_eq!(killed, 1);

    timeout(Duration::from_secs(15), async {
        loop {
            if let Ok(value) = shared.get::<_, String>(&key).await {
                assert_eq!(value, "cached");
                break;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .expect("the original clone should reconnect without recreating the cache");
    assert_eq!(cache.get::<_, String>(&key).await.unwrap(), "cached");
    cache.del::<_, ()>(&key).await.unwrap();
}

#[tokio::test]
#[ignore = "forces failover in disposable Sentinel fixtures created by api-rs/scripts/test-redis.sh"]
async fn sentinel_rediscovers_the_primary_after_failover() {
    let blackhole = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let blackhole_address = blackhole.local_addr().unwrap();
    // Keep accepted sockets open without replying. Dropping the JoinSet at the
    // end of the test aborts the task and closes every socket, even on panic.
    let mut blackhole_tasks = tokio::task::JoinSet::<()>::new();
    blackhole_tasks.spawn(async move {
        let mut connections = Vec::new();
        loop {
            let (connection, _) = blackhole.accept().await.unwrap();
            connections.push(connection);
        }
    });

    let mut config = config(fixture_port(1));
    config.sentinel = true;
    config.sentinel_master_name = "api-rs-test".into();
    config.sentinel_nodes = vec![
        blackhole_address.to_string(),
        format!("127.0.0.1:{}", fixture_port(4)),
        format!("127.0.0.1:{}", fixture_port(5)),
        format!("127.0.0.1:{}", fixture_port(6)),
    ];
    config.sentinel_password = Some(SENTINEL_PASSWORD.into());
    config.socket_connect_timeout = Some(0.5);
    let mut cache = timeout(Duration::from_secs(3), connect(&config))
        .await
        .expect("a blackholed first Sentinel must not block discovery through a healthy seed")
        .unwrap();
    let mut shared = cache.clone();
    let key = format!("api-rs-test:{}", Uuid::now_v7());
    let counter_key = format!("api-rs-test:no-replay:{}", Uuid::now_v7());
    let original_id = client_id(&mut cache).await;

    // Service errors arrive as Value::ServerError at the low-level v2 API.
    // Invalidate the shared connection and return the error without replaying
    // a command whose write has already completed.
    let error = redis::cmd("EVAL")
        .arg("redis.call('INCR', KEYS[1]); return redis.error_reply('READONLY regression')")
        .arg(1)
        .arg(&counter_key)
        .query_async::<()>(&mut shared)
        .await
        .unwrap_err();
    assert_eq!(error.code(), Some("READONLY"));
    let recovered_id = client_id(&mut cache).await;
    assert_ne!(recovered_id, original_id);
    assert_eq!(client_id(&mut shared).await, recovered_id);
    assert_eq!(shared.get::<_, i64>(&counter_key).await.unwrap(), 1);

    let result = redis::pipe()
        .cmd("EVAL")
        .arg("redis.call('INCR', KEYS[1]); return redis.error_reply('MASTERDOWN regression')")
        .arg(1)
        .arg(&counter_key)
        .cmd("PING")
        .query_async::<((), String)>(&mut cache)
        .await;
    assert!(result.is_err());
    let pipeline_recovered_id = client_id(&mut shared).await;
    assert_ne!(pipeline_recovered_id, recovered_id);
    assert_eq!(client_id(&mut cache).await, pipeline_recovered_id);
    assert_eq!(cache.get::<_, i64>(&counter_key).await.unwrap(), 2);
    cache.del::<_, ()>(&counter_key).await.unwrap();

    cache.set::<_, _, ()>(&key, "before").await.unwrap();
    let replicas: i64 = redis::cmd("WAIT")
        .arg(2)
        .arg(5_000)
        .query_async(&mut cache)
        .await
        .unwrap();
    assert_eq!(replicas, 2, "the primary must replicate to both replicas");

    // Three Sentinels use quorum 2. Take one down while keeping two voters
    // available; the same cache object must still rediscover the primary.
    let mut unavailable_sentinel = admin(fixture_port(6), SENTINEL_PASSWORD).await;
    let shutdown = redis::cmd("SHUTDOWN")
        .arg("NOSAVE")
        .query_async::<()>(&mut unavailable_sentinel)
        .await;
    assert!(
        shutdown.is_err(),
        "shutdown should close the Sentinel socket"
    );

    let mut sentinel = admin(fixture_port(4), SENTINEL_PASSWORD).await;
    timeout(Duration::from_secs(10), async {
        loop {
            let quorum = redis::cmd("SENTINEL")
                .arg("CKQUORUM")
                .arg("api-rs-test")
                .query_async::<String>(&mut sentinel)
                .await;
            if quorum.is_ok_and(|status| status.starts_with("OK 2 usable Sentinels")) {
                break;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .expect("the two remaining Sentinels must retain quorum");
    let old_primary: (String, u16) = redis::cmd("SENTINEL")
        .arg("GET-MASTER-ADDR-BY-NAME")
        .arg("api-rs-test")
        .query_async(&mut sentinel)
        .await
        .unwrap();
    redis::cmd("SENTINEL")
        .arg("FAILOVER")
        .arg("api-rs-test")
        .query_async::<()>(&mut sentinel)
        .await
        .unwrap();

    let new_port = timeout(Duration::from_secs(30), async {
        loop {
            let primary: (String, u16) = redis::cmd("SENTINEL")
                .arg("GET-MASTER-ADDR-BY-NAME")
                .arg("api-rs-test")
                .query_async(&mut sentinel)
                .await
                .unwrap();
            if primary != old_primary {
                break primary.1;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .expect("Sentinel should promote the disposable replica");

    timeout(Duration::from_secs(30), async {
        loop {
            let info = redis::cmd("INFO")
                .arg("SERVER")
                .query_async::<String>(&mut shared)
                .await;
            if let Ok(info) = info
                && info
                    .lines()
                    .any(|line| line == format!("tcp_port:{new_port}"))
                && shared.set::<_, _, ()>(&key, "after").await.is_ok()
            {
                break;
            }
            sleep(Duration::from_millis(100)).await;
        }
    })
    .await
    .expect("the original cache clone should discover and write to the new primary");
    let mut new_primary = admin(new_port, REDIS_PASSWORD).await;
    assert_eq!(new_primary.get::<_, String>(&key).await.unwrap(), "after");
    assert_eq!(cache.get::<_, String>(&key).await.unwrap(), "after");
    cache.del::<_, ()>(&key).await.unwrap();
}
