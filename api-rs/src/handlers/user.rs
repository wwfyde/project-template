use crate::models::user::{User, UserId};
use crate::repositories::orm::SeaOrmUserRepository;
pub(crate) use crate::schemas::user::{CreateUser, UserResponse};
use crate::services::user::UserService;
use crate::state::AppState;
use crate::utils;
use axum::Json;
use axum::extract::{Path, State};
use http::StatusCode;
use std::sync::Arc;
use uuid::Uuid;

use crate::services::auth_extractor::AuthUser;

/// 通过这种方式为API添加文档注释
#[utoipa::path(
    get,
    path = "/users",
    tags = ["user", "default"],
    summary = "获取所有用户",
    description = "Get all users",
    responses(
        (status = 200, description = "JSON file", body = [UserResponse]),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
    ),
    security(
        ("api_key" = [], "jwt_auth" = [])
    )
)]
/// 获取所有用户
pub async fn get_users(
    State(state): State<Arc<AppState>>,
    _auth_user: AuthUser,
) -> Result<Json<Vec<UserResponse>>, StatusCode> {
    let repo = Arc::new(SeaOrmUserRepository::new(state.db.clone()));
    let service = UserService::new(repo);
    let users = service.find_all().await?;

    let response = users.into_iter().map(UserResponse::from).collect();
    Ok(Json(response))
}

#[utoipa::path(
    post,
    path = "/users",
    tags = ["user"],
    summary = "新建用户",
    request_body = CreateUser,
    responses(
        (status = 201, description = "Created user", body = UserResponse),
        (status = 401, description = "Unauthorized"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [], "jwt_auth" = [])
    )
)]
pub async fn create_user(
    // this argument tells axum to parse the request body
    // as JSON into a `CreateUser` type
    State(state): State<Arc<AppState>>,
    _auth_user: AuthUser,

    Json(payload): Json<CreateUser>,
) -> Result<(StatusCode, Json<UserResponse>), StatusCode> {
    let repo = Arc::new(SeaOrmUserRepository::new(state.db.clone()));
    let service = UserService::new(repo);
    let now = chrono::Utc::now();
    let hashed_password =
        tokio::task::spawn_blocking(move || utils::get_password_hash(&payload.password))
            .await
            .map_err(|error| {
                tracing::error!(%error, "password hashing task failed");
                StatusCode::INTERNAL_SERVER_ERROR
            })?
            .map_err(|error| {
                tracing::error!(%error, "failed to hash password");
                StatusCode::INTERNAL_SERVER_ERROR
            })?;
    let new_user = User {
        id: UserId(Uuid::now_v7()),
        email: Some(payload.email),
        username: Some(payload.username),
        hashed_password: Some(hashed_password),
        is_active: Some(true),
        is_superuser: Some(false),
        created_at: now,
        updated_at: None,
    };

    let saved = service.create(new_user).await?;

    let response = UserResponse::from(saved);

    Ok((StatusCode::CREATED, Json(response)))
}

#[utoipa::path(
    get,
    path = "/users/{id}",
    tag = "user",
    params(("id" = Uuid, Path, description = "user id")),
    responses(
        (status = 200, description = "获取用户", body = UserResponse),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 404, description = "User not found"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [], "jwt_auth" = [])
    )
)]
/// 获取单个用户。
pub async fn get_user(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    _auth_user: AuthUser,
) -> Result<Json<UserResponse>, StatusCode> {
    let repo = Arc::new(SeaOrmUserRepository::new(state.db.clone()));
    let service = UserService::new(repo);
    let user = service.find_by_id(UserId(id)).await?;

    match user {
        Some(user) => Ok(Json(UserResponse::from(user))),
        None => Err(StatusCode::NOT_FOUND),
    }
}

#[utoipa::path(
    get,
    path = "/users/me",
    tag = "user",
    summary = "获取当前用户",
    responses(
        (status = 200, description = "Current user", body = UserResponse),
        (status = 401, description = "Unauthorized"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [], "jwt_auth" = [])
    )
)]
pub async fn get_current_user(
    State(state): State<Arc<AppState>>,
    auth_user: AuthUser,
) -> Result<Json<UserResponse>, crate::error::AuthError> {
    let user = state
        .auth
        .active_user_by_username(&state.db, &auth_user.username)
        .await?;
    Ok(Json(UserResponse::from(User::from(user))))
}
