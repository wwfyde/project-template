use crate::core::cache::CacheConnection;
use crate::services::auth::AuthService;
use axum::extract::FromRef;
use sea_orm::DatabaseConnection;
use std::sync::Arc;

#[derive(Clone, FromRef)]
pub struct AppState {
    pub db: Arc<DatabaseConnection>,
    pub http: reqwest::Client,
    pub auth: Arc<AuthService>,
    pub cache: Option<CacheConnection>,
}
