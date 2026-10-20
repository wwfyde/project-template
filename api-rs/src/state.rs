use std::sync::Arc;

use crate::services::auth::AuthService;
use sea_orm::DatabaseConnection;

pub struct AppState {
    pub db: Arc<DatabaseConnection>,
    pub auth: Arc<AuthService>,
}
