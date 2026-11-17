use std::sync::Arc;

use axum::Json;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use uuid::Uuid;

use crate::AppState;
use crate::models::shared::AccountId;
use crate::models::tenant::TenantId;
use crate::models::user::UserId;
use crate::repositories::orm::SeaOrmAccountRepository;
use crate::schemas::account::{
    AccountContextResponse, AccountMemberResponse, AccountResponse, CreateWorkspace, SetMemberRole,
};
use crate::services::account::AccountService;
use crate::services::auth_extractor::{AccountContext, AuthUser};

pub(super) fn service(state: &AppState) -> AccountService {
    AccountService::new(Arc::new(SeaOrmAccountRepository::new(state.db.clone())))
}

#[utoipa::path(
    get, path = "/accounts", tag = "account",
    summary = "列出当前用户可访问的账户",
    responses((status = 200, body = [AccountResponse]), (status = 401), (status = 403)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn list_accounts(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
) -> Result<Json<Vec<AccountResponse>>, StatusCode> {
    Ok(Json(
        service(&state)
            .list_accounts(UserId(auth.user_id))
            .await?
            .into_iter()
            .map(Into::into)
            .collect(),
    ))
}

#[utoipa::path(
    get, path = "/accounts/current", tag = "account",
    summary = "解析本次请求的账户与计费租户",
    params(("X-Account-Id" = Option<Uuid>, Header, description = "省略时使用个人账户；选择其他账户必须具有成员权限")),
    responses((status = 200, body = AccountContextResponse), (status = 400), (status = 401), (status = 403), (status = 404)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn current_account(
    AccountContext(access): AccountContext,
) -> Json<AccountContextResponse> {
    Json(access.into())
}

#[utoipa::path(
    get, path = "/accounts/{account_id}", tag = "account",
    params(("account_id" = Uuid, Path)),
    responses((status = 200, body = AccountResponse), (status = 401), (status = 403), (status = 404)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn get_account(
    State(state): State<Arc<AppState>>,
    Path(account_id): Path<Uuid>,
    auth: AuthUser,
) -> Result<Json<AccountResponse>, StatusCode> {
    Ok(Json(
        service(&state)
            .get_account(UserId(auth.user_id), AccountId(account_id))
            .await?
            .into(),
    ))
}

#[utoipa::path(
    post, path = "/tenants/{tenant_id}/accounts", tag = "account",
    summary = "在组织租户中创建 workspace 账户",
    params(("tenant_id" = Uuid, Path)), request_body = CreateWorkspace,
    responses((status = 201, body = AccountResponse), (status = 400), (status = 401), (status = 403), (status = 404)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn create_workspace(
    State(state): State<Arc<AppState>>,
    Path(tenant_id): Path<Uuid>,
    auth: AuthUser,
    Json(input): Json<CreateWorkspace>,
) -> Result<(StatusCode, Json<AccountResponse>), StatusCode> {
    let account = service(&state)
        .create_workspace(UserId(auth.user_id), TenantId(tenant_id), &input.name)
        .await?;
    Ok((StatusCode::CREATED, Json(account.into())))
}

#[utoipa::path(
    get, path = "/accounts/{account_id}/members", tag = "account", operation_id = "list_account_members",
    params(("account_id" = Uuid, Path)),
    responses((status = 200, body = [AccountMemberResponse]), (status = 401), (status = 403), (status = 404)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn list_members(
    State(state): State<Arc<AppState>>,
    Path(account_id): Path<Uuid>,
    auth: AuthUser,
) -> Result<Json<Vec<AccountMemberResponse>>, StatusCode> {
    Ok(Json(
        service(&state)
            .account_members(UserId(auth.user_id), AccountId(account_id))
            .await?
            .into_iter()
            .map(Into::into)
            .collect(),
    ))
}

#[utoipa::path(
    put, path = "/accounts/{account_id}/members/{user_id}", tag = "account", operation_id = "put_account_member",
    description = "目标用户须先加入所属 tenant；个人账户不可添加他人。Owner 可管理角色，Admin 只可管理普通成员。",
    params(("account_id" = Uuid, Path), ("user_id" = Uuid, Path)), request_body = SetMemberRole,
    responses((status = 200, body = AccountMemberResponse), (status = 400), (status = 401), (status = 403), (status = 404), (status = 409)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn put_member(
    State(state): State<Arc<AppState>>,
    Path((account_id, user_id)): Path<(Uuid, Uuid)>,
    auth: AuthUser,
    Json(input): Json<SetMemberRole>,
) -> Result<Json<AccountMemberResponse>, StatusCode> {
    Ok(Json(
        service(&state)
            .put_account_member(
                UserId(auth.user_id),
                AccountId(account_id),
                UserId(user_id),
                input.role.into(),
            )
            .await?
            .into(),
    ))
}

#[utoipa::path(
    delete, path = "/accounts/{account_id}/members/{user_id}", tag = "account", operation_id = "remove_account_member",
    description = "撤销账户访问；最后一名 Owner 必须先转移所有权。",
    params(("account_id" = Uuid, Path), ("user_id" = Uuid, Path)),
    responses((status = 204), (status = 401), (status = 403), (status = 404), (status = 409)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn remove_member(
    State(state): State<Arc<AppState>>,
    Path((account_id, user_id)): Path<(Uuid, Uuid)>,
    auth: AuthUser,
) -> Result<StatusCode, StatusCode> {
    service(&state)
        .remove_account_member(UserId(auth.user_id), AccountId(account_id), UserId(user_id))
        .await?;
    Ok(StatusCode::NO_CONTENT)
}
