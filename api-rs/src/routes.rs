use crate::AppState;
use crate::handlers;
use axum::Router;
use std::sync::Arc;
use utoipa::OpenApi;

pub mod auth;
pub mod item;
pub mod misc;
pub mod user;

#[derive(OpenApi)]
#[openapi(paths(
    handlers::user::get_users,
    handlers::user::get_user,
    handlers::user::get_current_user,
    handlers::user::create_user,
    handlers::item::get_items,
    handlers::item::get_item,
    handlers::item::create_item,
    handlers::item::update_item,
    handlers::item::delete_item,
    auth::login_for_access_token,
))]
pub struct AllApi;

pub fn all_routes() -> Router<Arc<AppState>> {
    Router::new().nest(
        "/api",
        Router::new()
            .merge(user::user_routes())
            .merge(item::item_routes())
            .merge(auth::auth_routes()),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn openapi_matches_user_routes_and_authentication() {
        let document = serde_json::to_value(AllApi::openapi()).expect("serialize OpenAPI");
        for path in ["/users", "/users/{id}", "/users/me"] {
            assert_eq!(
                document["paths"][path]["get"]["security"],
                json!([{"api_key": [], "jwt_auth": []}]),
                "{path} requires both credentials"
            );
        }
        assert!(
            document["paths"]["/users"]["post"]["responses"]
                .get("201")
                .is_some()
        );
        assert!(document["paths"]["/users/{id}"].get("put").is_none());
        assert!(document["paths"]["/users/{id}"].get("delete").is_none());
    }
}
