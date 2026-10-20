use crate::AppState;
use crate::handlers::user::{create_user, get_current_user, get_user, get_users};
use axum::Router;
use axum::routing::get;
use std::sync::Arc;

pub fn user_routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/users", get(get_users).post(create_user))
        .route("/users/me", get(get_current_user))
        .route("/users/{id}", get(get_user))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::services::auth::AuthService;
    use axum::body::Body;
    use axum::http::{Method, Request, StatusCode};
    use sea_orm::{ConnectOptions, Database};
    use tower::ServiceExt;

    async fn app() -> Router {
        let mut options = ConnectOptions::new("postgres://test:test@127.0.0.1:1/test");
        options.connect_lazy(true);
        let db = Database::connect(options)
            .await
            .expect("lazy database connection");
        user_routes().with_state(Arc::new(AppState {
            db: Arc::new(db),
            auth: Arc::new(AuthService::new(
                "test-api-key".to_string(),
                "test-jwt-secret-with-at-least-32-characters".to_string(),
                1,
            )),
        }))
    }

    #[tokio::test]
    async fn users_and_current_user_require_authentication() {
        let app = app().await;
        for path in [
            "/users",
            "/users/me",
            "/users/00000000-0000-0000-0000-000000000001",
        ] {
            let response = app
                .clone()
                .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
        }
    }

    #[tokio::test]
    async fn user_routes_do_not_mutate_items() {
        let app = app().await;
        for method in [Method::PUT, Method::DELETE] {
            let response = app
                .clone()
                .oneshot(
                    Request::builder()
                        .method(method.clone())
                        .uri("/users/00000000-0000-0000-0000-000000000001")
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(
                response.status(),
                StatusCode::METHOD_NOT_ALLOWED,
                "{method}"
            );
        }
    }
}
