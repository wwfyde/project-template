use crate::models::user::{User, UserId, UserWrite};
use crate::repositories::orm::{SeaOrmAccountRepository, SeaOrmUserRepository};
pub(crate) use crate::schemas::user::{CreateUser, UserResponse};
use crate::services::account::AccountService;
use crate::services::user::UserService;
use crate::state::AppState;
use crate::utils;
use axum::Json;
use axum::extract::{Path, State};
use http::StatusCode;
use std::sync::Arc;
use uuid::Uuid;

use crate::services::auth_extractor::{AccountContext, ApiKeyAuth, AuthUser};

/// 通过这种方式为API添加文档注释
#[utoipa::path(
    get,
    path = "/users",
    tags = ["user", "default"],
    summary = "获取当前账户的成员用户",
    params(("X-Account-Id" = Option<Uuid>, Header, description = "资源账户，省略时使用个人账户")),
    responses(
        (status = 200, description = "JSON file", body = [UserResponse]),
        (status = 400, description = "Invalid account selection"),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 404, description = "Account not found"),
    ),
    security(
        ("api_key" = [], "jwt_auth" = [])
    )
)]
/// The selected account bounds the user directory as well as resource access.
pub async fn get_users(
    State(state): State<Arc<AppState>>,
    AccountContext(access): AccountContext,
) -> Result<Json<Vec<UserResponse>>, StatusCode> {
    let repo = Arc::new(SeaOrmUserRepository::new(state.db.clone()));
    let service = UserService::new(repo);
    let accounts = AccountService::new(Arc::new(SeaOrmAccountRepository::new(state.db.clone())));
    let members = accounts
        .account_members(access.user_id, access.account_id)
        .await?;
    let ids: Vec<_> = members.into_iter().map(|member| member.user_id).collect();
    let mut users = Vec::new();
    for batch in ids.chunks(1000) {
        users.extend(service.find_many(batch).await?);
    }

    let response = users.into_iter().map(UserResponse::from).collect();
    Ok(Json(response))
}

#[utoipa::path(
    post,
    path = "/users",
    tags = ["user"],
    summary = "新建用户",
    description = "使用 X-Api-Key 原子创建用户、个人计费租户及个人账户，无需先登录。",
    request_body = CreateUser,
    responses(
        (status = 201, description = "Created user", body = UserResponse),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 409, description = "Email or username already exists"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
pub async fn create_user(
    // this argument tells axum to parse the request body
    // as JSON into a `CreateUser` type
    State(state): State<Arc<AppState>>,
    _api_key: ApiKeyAuth,
    Json(payload): Json<CreateUser>,
) -> Result<(StatusCode, Json<UserResponse>), StatusCode> {
    let repo = Arc::new(SeaOrmAccountRepository::new(state.db.clone()));
    let service = AccountService::new(repo);
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
    let new_user = UserWrite {
        id: UserId(Uuid::now_v7()),
        email: Some(payload.email),
        nickname: payload.nickname,
        username: Some(payload.username),
        hashed_password: Some(hashed_password),
        is_active: Some(true),
        locale: payload.locale,
        is_superuser: Some(false),
        created_at: now,
        updated_at: None,
    };

    let saved = service.register_user(&new_user).await?;

    let response = UserResponse::from(saved);

    Ok((StatusCode::CREATED, Json(response)))
}

#[utoipa::path(
    get,
    path = "/users/{id}",
    tag = "user",
    params(
        ("id" = Uuid, Path, description = "user id"),
        ("X-Account-Id" = Option<Uuid>, Header, description = "资源账户，省略时使用个人账户")
    ),
    responses(
        (status = 200, description = "获取用户", body = UserResponse),
        (status = 400, description = "Invalid account selection"),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 403, description = "Account access denied"),
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
    AccountContext(access): AccountContext,
) -> Result<Json<UserResponse>, StatusCode> {
    let repo = Arc::new(SeaOrmUserRepository::new(state.db.clone()));
    let service = UserService::new(repo);
    let accounts = AccountService::new(Arc::new(SeaOrmAccountRepository::new(state.db.clone())));
    let members = accounts
        .account_members(access.user_id, access.account_id)
        .await?;
    if !members.iter().any(|member| member.user_id.0 == id) {
        return Err(StatusCode::NOT_FOUND);
    }
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
        .active_user_by_id(&state.db, auth_user.user_id)
        .await?;
    let user = User::try_from(user).map_err(|error| {
        tracing::error!(?error, "invalid stored user profile");
        crate::error::AuthError::InternalServerError
    })?;
    Ok(Json(UserResponse::from(user)))
}
