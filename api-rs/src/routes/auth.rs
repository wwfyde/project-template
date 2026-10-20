use crate::AppState;
use crate::error::AuthError;
use axum::{
    Json, Router,
    extract::{Form, State},
    routing::post,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use utoipa::ToSchema;

#[derive(Deserialize, ToSchema)]
pub struct OAuth2PasswordRequestForm {
    pub username: String,
    pub password: String,
}

#[derive(Serialize, ToSchema)]
pub struct Token {
    pub access_token: String,
    pub token_type: String,
    /// Access token lifetime in seconds.
    pub expires_in: i64,
}

pub fn auth_routes() -> Router<Arc<AppState>> {
    Router::new().route("/auth/token", post(login_for_access_token))
}

#[utoipa::path(
    post,
    path = "/auth/token",
    request_body(content = OAuth2PasswordRequestForm, content_type = "application/x-www-form-urlencoded"),
    responses(
        (status = 200, description = "Login success", body = Token),
        (status = 401, description = "Unauthorized", body = AuthError),
        (status = 500, description = "Internal server error")
    )
)]
pub async fn login_for_access_token(
    State(state): State<Arc<AppState>>,
    Form(form_data): Form<OAuth2PasswordRequestForm>,
) -> Result<Json<Token>, AuthError> {
    let user = state
        .auth
        .authenticate_user(&state.db, &form_data.username, &form_data.password)
        .await?;
    let username = user
        .username
        .ok_or_else(|| AuthError::Unauthorized("User has no username".to_string()))?;
    let access_token = state.auth.create_access_token(&username)?;
    let expires_in = state.auth.access_token_lifetime_seconds()?;

    Ok(Json(Token {
        access_token,
        token_type: "bearer".to_string(),
        expires_in,
    }))
}
