use crate::AppState;
use crate::handlers::item::{create_item, delete_item, get_item, get_items, update_item};
use axum::Router;
use axum::routing::get;
use std::sync::Arc;

pub fn item_routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/items", get(get_items).post(create_item))
        .route(
            "/items/{id}",
            get(get_item).put(update_item).delete(delete_item),
        )
}
