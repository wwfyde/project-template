use std::sync::Arc;

use axum::Json;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use uuid::Uuid;

use super::account::service;
use crate::AppState;
use crate::models::tenant::TenantId;
use crate::models::user::UserId;
use crate::schemas::account::SetMemberRole;
use crate::schemas::tenant::{CreateTenant, TenantMemberResponse, TenantResponse};
use crate::services::auth_extractor::AuthUser;

#[utoipa::path(
    get, path = "/tenants", tag = "tenant",
    summary = "列出当前用户加入的计费租户",
    responses((status = 200, body = [TenantResponse]), (status = 401), (status = 403)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn list_tenants(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
) -> Result<Json<Vec<TenantResponse>>, StatusCode> {
    Ok(Json(
        service(&state)
            .list_tenants(UserId(auth.user_id))
            .await?
            .into_iter()
            .map(Into::into)
            .collect(),
    ))
}

#[utoipa::path(
    post, path = "/tenants", tag = "tenant",
    summary = "创建组织计费租户并成为 Owner",
    request_body = CreateTenant,
    responses((status = 201, body = TenantResponse), (status = 400), (status = 401), (status = 403)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn create_tenant(
    State(state): State<Arc<AppState>>,
    auth: AuthUser,
    Json(input): Json<CreateTenant>,
) -> Result<(StatusCode, Json<TenantResponse>), StatusCode> {
    let tenant = service(&state)
        .create_tenant(UserId(auth.user_id), &input.name)
        .await?;
    Ok((StatusCode::CREATED, Json(tenant.into())))
}

#[utoipa::path(
    get, path = "/tenants/{tenant_id}/members", tag = "tenant", operation_id = "list_tenant_members",
    params(("tenant_id" = Uuid, Path)),
    responses((status = 200, body = [TenantMemberResponse]), (status = 401), (status = 403), (status = 404)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn list_members(
    State(state): State<Arc<AppState>>,
    Path(tenant_id): Path<Uuid>,
    auth: AuthUser,
) -> Result<Json<Vec<TenantMemberResponse>>, StatusCode> {
    Ok(Json(
        service(&state)
            .tenant_members(UserId(auth.user_id), TenantId(tenant_id))
            .await?
            .into_iter()
            .map(Into::into)
            .collect(),
    ))
}

#[utoipa::path(
    put, path = "/tenants/{tenant_id}/members/{user_id}", tag = "tenant", operation_id = "put_tenant_member",
    description = "加入已有用户；组织成员资格不自动授予任何 workspace 资源访问。",
    params(("tenant_id" = Uuid, Path), ("user_id" = Uuid, Path)), request_body = SetMemberRole,
    responses((status = 200, body = TenantMemberResponse), (status = 400), (status = 401), (status = 403), (status = 404), (status = 409)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn put_member(
    State(state): State<Arc<AppState>>,
    Path((tenant_id, user_id)): Path<(Uuid, Uuid)>,
    auth: AuthUser,
    Json(input): Json<SetMemberRole>,
) -> Result<Json<TenantMemberResponse>, StatusCode> {
    Ok(Json(
        service(&state)
            .put_tenant_member(
                UserId(auth.user_id),
                TenantId(tenant_id),
                UserId(user_id),
                input.role.into(),
            )
            .await?
            .into(),
    ))
}

#[utoipa::path(
    delete, path = "/tenants/{tenant_id}/members/{user_id}", tag = "tenant", operation_id = "remove_tenant_member",
    description = "同时移除该租户内的账户成员关系；不得移除租户或任一 workspace 的最后一名 Owner。",
    params(("tenant_id" = Uuid, Path), ("user_id" = Uuid, Path)),
    responses((status = 204), (status = 401), (status = 403), (status = 404), (status = 409)),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn remove_member(
    State(state): State<Arc<AppState>>,
    Path((tenant_id, user_id)): Path<(Uuid, Uuid)>,
    auth: AuthUser,
) -> Result<StatusCode, StatusCode> {
    service(&state)
        .remove_tenant_member(UserId(auth.user_id), TenantId(tenant_id), UserId(user_id))
        .await?;
    Ok(StatusCode::NO_CONTENT)
}
