use crate::AppState;
use crate::schemas::item::{CreateItem, Item, UpdateItem};
use crate::services::auth_extractor::AccountContext;
use crate::services::item::ItemService;
use axum::http::StatusCode;
use axum::{
    Json,
    extract::{Path, State},
};
use std::sync::Arc;
use uuid::Uuid;

#[utoipa::path(
    get,
    path = "/items",
    tag = "item",
    params(("X-Account-Id" = Option<Uuid>, Header, description = "Account to access; defaults to the authenticated user's personal account")),
    responses(
        (status = 200, description = "Items in the selected account", body = [Item]),
        (status = 400, description = "Invalid or repeated account header"),
        (status = 401, description = "API key or bearer token missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 500, description = "Internal server error")
    ),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn get_items(
    State(state): State<Arc<AppState>>,
    AccountContext(access): AccountContext,
) -> Result<Json<Vec<Item>>, StatusCode> {
    let service = ItemService::new(state.db.clone(), access);
    Ok(Json(service.find_all().await?))
}

#[utoipa::path(
    get,
    path = "/items/{id}",
    tag = "item",
    params(
        ("id" = Uuid, Path, description = "Item ID"),
        ("X-Account-Id" = Option<Uuid>, Header, description = "Account to access; defaults to the authenticated user's personal account")
    ),
    responses(
        (status = 200, description = "Item in the selected account", body = Item),
        (status = 400, description = "Invalid account header"),
        (status = 401, description = "API key or bearer token missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 404, description = "Item not found in this account"),
        (status = 500, description = "Internal server error")
    ),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn get_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    AccountContext(access): AccountContext,
) -> Result<Json<Item>, StatusCode> {
    let service = ItemService::new(state.db.clone(), access);
    service
        .find_by_id(id)
        .await?
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

#[utoipa::path(
    post,
    path = "/items",
    tag = "item",
    params(("X-Account-Id" = Option<Uuid>, Header, description = "Account to access; defaults to the authenticated user's personal account")),
    request_body = CreateItem,
    responses(
        (status = 201, description = "Item created in the selected account", body = Item),
        (status = 400, description = "Invalid account header or malformed JSON"),
        (status = 422, description = "Invalid item payload"),
        (status = 401, description = "API key or bearer token missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 500, description = "Internal server error")
    ),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn create_item(
    State(state): State<Arc<AppState>>,
    AccountContext(access): AccountContext,
    Json(payload): Json<CreateItem>,
) -> Result<(StatusCode, Json<Item>), StatusCode> {
    let service = ItemService::new(state.db.clone(), access);
    Ok((StatusCode::CREATED, Json(service.create(payload).await?)))
}

#[utoipa::path(
    put,
    path = "/items/{id}",
    tag = "item",
    request_body = UpdateItem,
    params(
        ("id" = Uuid, Path, description = "Item ID"),
        ("X-Account-Id" = Option<Uuid>, Header, description = "Account to access; defaults to the authenticated user's personal account")
    ),
    responses(
        (status = 200, description = "Item updated without changing its account or creator", body = Item),
        (status = 400, description = "Invalid account header or malformed JSON"),
        (status = 422, description = "Invalid item payload"),
        (status = 401, description = "API key or bearer token missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 404, description = "Item not found in this account"),
        (status = 500, description = "Internal server error")
    ),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn update_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    AccountContext(access): AccountContext,
    Json(payload): Json<UpdateItem>,
) -> Result<Json<Item>, StatusCode> {
    let service = ItemService::new(state.db.clone(), access);
    service
        .update(id, payload)
        .await?
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

#[utoipa::path(
    delete,
    path = "/items/{id}",
    tag = "item",
    params(
        ("id" = Uuid, Path, description = "Item ID"),
        ("X-Account-Id" = Option<Uuid>, Header, description = "Account to access; defaults to the authenticated user's personal account")
    ),
    responses(
        (status = 204, description = "Item deleted from the selected account"),
        (status = 400, description = "Invalid account header"),
        (status = 401, description = "API key or bearer token missing or invalid"),
        (status = 403, description = "Account access denied"),
        (status = 404, description = "Item not found in this account"),
        (status = 500, description = "Internal server error")
    ),
    security(("api_key" = [], "jwt_auth" = []))
)]
pub async fn delete_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    AccountContext(access): AccountContext,
) -> Result<StatusCode, StatusCode> {
    let service = ItemService::new(state.db.clone(), access);
    if service.delete(id).await? {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(StatusCode::NOT_FOUND)
    }
}
