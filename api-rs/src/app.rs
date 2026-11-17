use crate::config::load_config;
use crate::{core, routes};
use anyhow::Context;
use axum::response::Redirect;
use axum::{
    Json, Router,
    http::header::{AUTHORIZATION, CONTENT_TYPE, HeaderName},
    routing::get,
};
use clap::Parser;

use crate::error::AuthError;
use crate::services::auth::AuthService;
use crate::state::AppState;
use serde_json::{Value, json};
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use utoipa::openapi::security::{ApiKey, ApiKeyValue, Scopes, SecurityScheme};
use utoipa::{Modify, OpenApi};
use utoipa_swagger_ui::SwaggerUi;

#[derive(OpenApi)]
#[openapi(
    modifiers(&SecurityAddon),
    paths(
        routes::misc::root,
        health_check,
    ),
    nest(
    (path="/api", api=routes::AllApi)
    ),
    components(
        schemas(AuthError),
        schemas(routes::auth::Token, routes::auth::OAuth2PasswordRequestForm)
    ),
)]
struct ApiDoc;
struct SecurityAddon;

impl Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        let name = "X-Api-Key";
        let description = "API Key Token with Http Header";
        let api_token = ApiKey::Header(ApiKeyValue::with_description(name, description));
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme("api_key", SecurityScheme::ApiKey(api_token));
        }
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "jwt_auth",
                SecurityScheme::OAuth2(utoipa::openapi::security::OAuth2::new([
                    utoipa::openapi::security::Flow::Password(
                        utoipa::openapi::security::Password::new("/api/auth/token", Scopes::new()),
                    ),
                ])),
            )
        }
    }
}

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// 监听端口：--port 优先于 API_PORT，再使用 app.port（默认 8000）
    #[arg(long, env = "API_PORT")]
    port: Option<u16>,
}

/// 初始化依赖并运行 HTTP 服务，收到退出信号后关闭数据库连接池。
pub async fn run() -> anyhow::Result<()> {
    let args = Args::parse();
    let config = load_config()?;
    let port = args.port.unwrap_or(config.app.port);
    let (api_key, jwt_secret, access_token_expire_days) = config.app.runtime_auth()?;

    // initialize tracing
    tracing_subscriber::fmt::init();

    let http = reqwest::Client::builder()
        .build()
        .context("failed to create HTTP client")?;

    let cache = match config.redis.as_ref() {
        Some(config) => {
            let connection = if config.sentinel {
                core::cache::CacheConnection::sentinel(config).await
            } else {
                core::cache::CacheConnection::standalone(config).await
            };
            Some(connection.context("failed to initialize Redis cache")?)
        }
        None => None,
    };

    let db = Arc::new(
        core::db::connect(config.postgres.connection_url()?, config.postgres.pool_size)
            .await
            .context("failed to connect to PostgreSQL")?,
    );

    // 执行数据库同步
    core::db::sync_schema(&db)
        .await
        .context("failed to synchronize PostgreSQL schema")?;

    // 创建认证服务
    let auth_service = Arc::new(AuthService::new(
        api_key,
        jwt_secret,
        access_token_expire_days,
    ));

    // 注入全局状态依赖
    let state = Arc::new(AppState {
        db: db.clone(),
        http,
        cache,
        auth: auth_service,
    });

    let app = build_app(state);
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .context("failed to bind HTTP listener")?;
    tracing::info!(address = %listener.local_addr()?, "listening");

    let result = axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await;
    db.close_by_ref()
        .await
        .context("failed to close database pool")?;
    result.context("HTTP server failed")
}

/// 使用已有状态组装路由，不加载配置或连接外部服务。
fn build_app(state: Arc<AppState>) -> Router {
    let doc = ApiDoc::openapi();
    Router::new()
        // Redirect to the API documentation
        .route("/", get(|| async { Redirect::permanent("/docs") }))
        .route("/root", get(routes::misc::root))
        // health check
        .route("/health", get(health_check))
        .merge(routes::all_routes())
        .merge(SwaggerUi::new("/docs").url("/api-docs/openapi.json", doc))
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers([
                    CONTENT_TYPE,
                    AUTHORIZATION,
                    HeaderName::from_static("x-api-key"),
                    HeaderName::from_static("x-account-id"),
                ]),
        )
        .with_state(state)
}

async fn shutdown_signal() {
    let ctrl_c = async {
        if let Err(error) = tokio::signal::ctrl_c().await {
            tracing::error!(%error, "failed to listen for Ctrl+C");
        }
    };
    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(error) => tracing::error!(%error, "failed to listen for SIGTERM"),
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
}

#[utoipa::path(
    get,
    path="/health",
    tags = ["default"],
    summary = "健康检查",
    description = "",
    responses(
        (status = 200, description = "Health Check", body= ())
    )
)]
pub async fn health_check() -> Json<Value> {
    Json(json!(
        {
            "status": "ok",
            "message":"Service is running"
    }))
}

#[cfg(test)]
mod tests;
