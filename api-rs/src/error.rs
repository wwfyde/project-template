use axum::Json;
use axum::response::{IntoResponse, Response};
use http::StatusCode;
use serde::{Deserialize, Serialize};
use serde_json::json;
use thiserror::Error;
use utoipa::ToSchema;

#[allow(dead_code)]
#[derive(Error, Debug)]
pub enum ApiError {
    #[error("SQL error: {0}")]
    SQL(#[from] sea_orm::DbErr),
}

#[derive(Debug, Serialize, Deserialize, ToSchema)]
pub enum AuthError {
    /// 未授权
    #[schema(example = "无效的API密钥")]
    Unauthorized(String),
    InternalServerError,
}

impl IntoResponse for AuthError {
    fn into_response(self) -> Response {
        let (status, error_message) = match self {
            Self::Unauthorized(message) => (StatusCode::UNAUTHORIZED, message),
            Self::InternalServerError => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Internal server error".to_string(),
            ),
        };
        (status, Json(json!({ "error": error_message }))).into_response()
    }
}
