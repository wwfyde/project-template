use crate::AppState;
use crate::schemas::item::{CreateItem, Item, UpdateItem};
use crate::services::item::ItemService;
use axum::http::{HeaderMap, StatusCode};
use axum::{
    Json, debug_handler,
    extract::{Path, State},
};
use std::sync::Arc;
use uuid::Uuid;

#[utoipa::path(
    get,
    path = "/items",
    tag = "item",
    responses(
        (status = 200, description = "获取所有 item", body = [Item]),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
/// 获取所有 item
pub async fn get_items(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Vec<Item>>, StatusCode> {
    // 验证API密钥
    state
        .auth
        .verify_api_key(&headers, true)
        .map_err(|(status, _)| status)?;

    let service = ItemService::new(state.db.clone());
    let items = service.find_all().await?;
    Ok(Json(items))
}

#[utoipa::path(
    get,
    path = "/items/{id}",
    tag = "item",
    params(("id" = Uuid, Path, description = "item id")),
    responses(
        (status = 200, description = "获取单个 item", body = Item),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 404, description = "Item not found"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
/// 获取单个 item
pub async fn get_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
) -> Result<Json<Item>, StatusCode> {
    // 验证API密钥
    state
        .auth
        .verify_api_key(&headers, true)
        .map_err(|(status, _)| status)?;

    let service = ItemService::new(state.db.clone());
    let item = service.find_by_id(id).await?;

    match item {
        Some(item) => Ok(Json(item)),
        None => Err(StatusCode::NOT_FOUND),
    }
}

#[debug_handler]
#[utoipa::path(
    post,
    path = "/items",
    tag = "item",
    request_body = CreateItem,
    responses(
        (status = 201, description = "创建 item", body = Item),
        (status = 400, description = "Malformed JSON"),
        (status = 422, description = "Invalid item payload"),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
/// 创建 item
pub async fn create_item(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(payload): Json<CreateItem>,
) -> Result<(StatusCode, Json<Item>), StatusCode> {
    // 验证API密钥
    state
        .auth
        .verify_api_key(&headers, true)
        .map_err(|(status, _)| status)?;

    let service = ItemService::new(state.db.clone());
    let item = service.create(payload).await?;
    Ok((StatusCode::CREATED, Json(item)))
}

#[debug_handler]
#[utoipa::path(
    put,
    path = "/items/{id}",
    tag = "item",
    request_body = UpdateItem,
    params(("id" = Uuid, Path, description = "item id")),
    responses(
        (status = 200, description = "更新 item", body = Item),
        (status = 400, description = "Malformed JSON or invalid UUID"),
        (status = 422, description = "Invalid item payload"),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 404, description = "Item not found"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
/// 更新 item
pub async fn update_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
    Json(payload): Json<UpdateItem>,
) -> Result<Json<Item>, StatusCode> {
    // 验证API密钥
    state
        .auth
        .verify_api_key(&headers, true)
        .map_err(|(status, _)| status)?;

    let service = ItemService::new(state.db.clone());

    match service.update(id, payload).await? {
        Some(item) => Ok(Json(item)),
        None => Err(StatusCode::NOT_FOUND),
    }
}

#[utoipa::path(
    delete,
    path = "/items/{id}",
    tag = "item",
    params(("id" = Uuid, Path, description = "item id")),
    responses(
        (status = 204, description = "删除 item"),
        (status = 401, description = "Unauthorized - API key missing or invalid"),
        (status = 404, description = "Item not found"),
        (status = 500, description = "Internal server error")
    ),
    security(
        ("api_key" = [])
    )
)]
/// 删除 item
pub async fn delete_item(
    State(state): State<Arc<AppState>>,
    Path(id): Path<Uuid>,
    headers: HeaderMap,
) -> Result<StatusCode, StatusCode> {
    // 验证API密钥
    state
        .auth
        .verify_api_key(&headers, true)
        .map_err(|(status, _)| status)?;

    let service = ItemService::new(state.db.clone());
    let deleted = service.delete(id).await?;

    if deleted {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(StatusCode::NOT_FOUND)
    }
}
