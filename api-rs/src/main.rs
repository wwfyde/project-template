pub mod config;
mod error;
pub mod handlers;
pub mod repositories;
pub mod routes;
pub mod schemas;
pub mod services;
mod state;

pub mod entities;

mod core;
mod middleware;
mod models;
mod telemetry;
pub mod utils;

use anyhow::Context;
use axum::response::Redirect;
use axum::{
    Json, Router,
    http::header::{AUTHORIZATION, CONTENT_TYPE, HeaderName},
    routing::get,
};
use clap::Parser;
use config::load_config;

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
    /// 监听端口：--port 优先于 API_PORT，默认 3000
    #[arg(long, env = "API_PORT", default_value_t = 3000)]
    port: u16,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Process environment > .env.local > .env.
    dotenvy::from_filename(".env.local").ok();
    dotenvy::dotenv().ok();
    let args = Args::parse();
    let config = load_config()?;

    // initialize tracing
    tracing_subscriber::fmt::init();

    let db = Arc::new(
        core::db::connect(config.postgres.connection_url()?)
            .await
            .context("failed to connect to PostgreSQL")?,
    );

    // 创建认证服务
    let api_key = config.app.api_key;
    let jwt_secret = config.app.jwt_secret.clone();
    let access_token_expire_days = config.app.access_token_expire_days;
    let auth_service = Arc::new(AuthService::new(
        api_key,
        jwt_secret,
        access_token_expire_days,
    ));

    // 注入全局状态依赖
    let state = Arc::new(AppState {
        db: db.clone(),
        auth: auth_service,
    });

    let app = build_app(state);
    let addr = format!("0.0.0.0:{}", args.port);
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
mod tests {
    use super::*;
    use axum::body::{Body, to_bytes};
    use axum::http::{Request, StatusCode};
    use sea_orm::Database;
    use tower::ServiceExt;

    async fn app() -> Router {
        build_app(Arc::new(AppState {
            db: Arc::new(Database::connect("sqlite::memory:").await.unwrap()),
            auth: Arc::new(AuthService::new(
                "test-key".into(),
                "test-jwt-secret-with-at-least-32-characters".into(),
                1,
            )),
        }))
    }

    #[tokio::test]
    async fn user_repository_and_current_user_round_trip() {
        use crate::models::user::{User, UserId, UserRepository};
        use crate::repositories::RepositoryError;
        use crate::repositories::orm::SeaOrmUserRepository;
        use sea_orm::{ConnectOptions, ConnectionTrait, Schema};
        use uuid::Uuid;

        let mut options = ConnectOptions::new("sqlite::memory:");
        options.max_connections(1);
        let db = Arc::new(Database::connect(options).await.unwrap());
        db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
            .await
            .unwrap();
        db.execute(
            &Schema::new(db.get_database_backend())
                .create_table_from_entity(entities::user::Entity),
        )
        .await
        .unwrap();
        let repo = SeaOrmUserRepository::new(db.clone());
        let original = User {
            id: UserId(Uuid::now_v7()),
            email: Some("alice@example.com".into()),
            username: Some("alice".into()),
            hashed_password: Some(bcrypt::hash("test-password", 4).unwrap()),
            is_active: Some(true),
            is_superuser: Some(false),
            created_at: chrono::Utc::now(),
            updated_at: None,
        };
        let saved = repo.insert(&original).await.unwrap();
        assert_eq!(
            repo.find_by_email("alice@example.com").await.unwrap(),
            Some(saved.clone())
        );
        assert_eq!(
            repo.find_by_id(saved.id.clone()).await.unwrap(),
            Some(saved.clone())
        );
        assert_eq!(repo.find_all().await.unwrap(), vec![saved.clone()]);

        let auth = Arc::new(AuthService::new(
            "test-key".into(),
            "test-jwt-secret-with-at-least-32-characters".into(),
            1,
        ));
        let app = build_app(Arc::new(AppState { db, auth }));
        let login = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/auth/token")
                    .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
                    .body(Body::from("username=alice&password=test-password"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(login.status(), StatusCode::OK);
        let token: Value =
            serde_json::from_slice(&to_bytes(login.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(token["expires_in"], 86_400);
        let current = app
            .oneshot(
                Request::builder()
                    .uri("/api/users/me")
                    .header("x-api-key", "test-key")
                    .header(
                        AUTHORIZATION,
                        format!("Bearer {}", token["access_token"].as_str().unwrap()),
                    )
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(current.status(), StatusCode::OK);
        let current: Value =
            serde_json::from_slice(&to_bytes(current.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(current["id"], saved.id.0.to_string());
        assert_eq!(current["username"], "alice");
        assert!(current.get("hashed_password").is_none());

        let mut update = saved.clone();
        update.email = Some("updated@example.com".into());
        update.created_at -= chrono::Duration::days(1);
        update.updated_at = Some(chrono::Utc::now());
        let updated = repo.update(&update).await.unwrap();
        assert_eq!(updated.created_at, saved.created_at);
        assert_eq!(updated.email, update.email);
        assert_eq!(updated.updated_at, update.updated_at);
        repo.delete_by_id(saved.id.clone()).await.unwrap();
        assert!(repo.find_by_id(saved.id.clone()).await.unwrap().is_none());
        for error in [
            repo.update(&saved).await.unwrap_err(),
            repo.delete_by_id(saved.id).await.unwrap_err(),
        ] {
            assert!(matches!(
                error.downcast_ref::<RepositoryError>(),
                Some(RepositoryError::NotFound)
            ));
        }
    }

    #[tokio::test]
    async fn health_and_openapi_are_served_without_configuration_or_external_services() {
        let app = app().await;
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&body).unwrap()["status"],
            "ok"
        );

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api-docs/openapi.json")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        let doc: Value = serde_json::from_slice(&body).unwrap();
        for path in [
            "/api/users",
            "/api/users/me",
            "/api/users/{id}",
            "/api/items",
            "/api/items/{id}",
            "/api/auth/token",
        ] {
            assert!(doc["paths"].get(path).is_some(), "missing {path}");
        }
    }

    #[tokio::test]
    async fn cors_preflight_allows_required_authentication_headers() {
        let response = app()
            .await
            .oneshot(
                Request::builder()
                    .method("OPTIONS")
                    .uri("/api/users")
                    .header("origin", "http://localhost:5173")
                    .header("access-control-request-method", "GET")
                    .header(
                        "access-control-request-headers",
                        "authorization,x-api-key,content-type",
                    )
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let allowed = response.headers()["access-control-allow-headers"]
            .to_str()
            .unwrap();
        for header in ["authorization", "x-api-key", "content-type"] {
            assert!(
                allowed.split(',').any(|value| value.trim() == header),
                "missing {header}"
            );
        }
    }
}
