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
    use crate::entities::user;
    use crate::services::auth::AuthService;
    use axum::body::{Body, to_bytes};
    use axum::http::{Method, Request, StatusCode, header};
    use sea_orm::{ConnectOptions, ConnectionTrait, Database, EntityTrait};
    use serde_json::{Value, json};
    use tower::ServiceExt;
    use uuid::Uuid;

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

    async fn database_app() -> (Router, Arc<AppState>) {
        let mut options = ConnectOptions::new("sqlite::memory:");
        options.max_connections(1);
        let db = Database::connect(options).await.unwrap();
        db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
            .await
            .unwrap();
        db.execute(&crate::repositories::orm::user::user_table_for_tests(
            db.get_database_backend(),
        ))
        .await
        .unwrap();
        let state = Arc::new(AppState {
            db: Arc::new(db),
            auth: Arc::new(AuthService::new(
                "test-api-key".to_string(),
                "test-jwt-secret-with-at-least-32-characters".to_string(),
                1,
            )),
        });
        let app = user_routes()
            .merge(crate::routes::auth::auth_routes())
            .with_state(state.clone());
        (app, state)
    }

    #[tokio::test]
    async fn users_and_current_user_require_authentication() {
        let app = app().await;
        for path in [
            "/users",
            "/users/me",
            "/users/00000000-0000-0000-0000-000000000001",
        ] {
            for api_key in [None, Some("test-api-key")] {
                let mut request = Request::builder().uri(path);
                if let Some(api_key) = api_key {
                    request = request.header("X-Api-Key", api_key);
                }
                let response = app
                    .clone()
                    .oneshot(request.body(Body::empty()).unwrap())
                    .await
                    .unwrap();
                assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
            }
        }
    }

    #[tokio::test]
    async fn create_user_requires_a_valid_api_key_even_with_a_bearer_token() {
        let (app, state) = database_app().await;
        let token = state.auth.create_access_token("alice").unwrap();
        for api_key in [None, Some(""), Some("wrong-key")] {
            for bearer in [None, Some(token.as_str())] {
                let mut request = Request::builder()
                    .method(Method::POST)
                    .uri("/users")
                    .header(header::CONTENT_TYPE, "application/json");
                if let Some(api_key) = api_key {
                    request = request.header("X-Api-Key", api_key);
                }
                if let Some(bearer) = bearer {
                    request = request.header(header::AUTHORIZATION, format!("Bearer {bearer}"));
                }
                let response = app
                    .clone()
                    .oneshot(
                        request
                            .body(Body::from(
                                json!({
                                    "username": "alice",
                                    "password": "test-password",
                                    "email": "alice@example.com"
                                })
                                .to_string(),
                            ))
                            .unwrap(),
                    )
                    .await
                    .unwrap();
                assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
            }
        }
        assert!(
            user::Entity::find()
                .all(&*state.db)
                .await
                .unwrap()
                .is_empty()
        );
    }

    #[tokio::test]
    async fn api_key_bootstraps_a_user_who_can_log_in() {
        let (app, state) = database_app().await;
        let payload = json!({
            "username": "alice",
            "password": "test-password",
            "email": "alice@example.com",
            "nickname": "Alice",
            "locale": "ja-JP"
        });
        let create_request = || {
            Request::builder()
                .method(Method::POST)
                .uri("/users")
                .header("X-Api-Key", "test-api-key")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(payload.to_string()))
                .unwrap()
        };
        let response = app.clone().oneshot(create_request()).await.unwrap();
        assert_eq!(response.status(), StatusCode::CREATED);
        let created: Value =
            serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        let id = Uuid::parse_str(created["id"].as_str().unwrap()).unwrap();
        assert_ne!(id, Uuid::nil());
        assert_eq!(created["username"], "alice");
        assert_eq!(created["email"], "alice@example.com");
        assert!(created["uid"].as_u64().is_some_and(|uid| uid > 0));
        assert_eq!(created["nickname"], "Alice");
        assert_eq!(created["locale"], "ja-JP");
        assert!(created.get("password").is_none());
        assert!(created.get("hashed_password").is_none());

        let stored = user::Entity::find_by_id(id)
            .one(&*state.db)
            .await
            .unwrap()
            .unwrap();
        let hashed = stored.hashed_password.as_deref().unwrap();
        assert_ne!(hashed, "test-password");
        assert!(crate::utils::security::verify_password(
            "test-password",
            hashed
        ));
        assert_eq!(stored.is_active, Some(true));
        assert_eq!(stored.is_superuser, Some(false));
        assert_eq!(stored.nickname.as_deref(), Some("Alice"));
        assert_eq!(stored.locale, "ja-JP");
        assert_eq!(created["uid"], stored.uid);

        let duplicate = app.clone().oneshot(create_request()).await.unwrap();
        assert_eq!(duplicate.status(), StatusCode::CONFLICT);

        // A different email must not bypass the independent username constraint.
        let mut username_conflict = payload.clone();
        username_conflict["email"] = json!("different@example.com");
        let duplicate_username = app
            .clone()
            .oneshot(
                Request::builder()
                    .method(Method::POST)
                    .uri("/users")
                    .header("X-Api-Key", "test-api-key")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(username_conflict.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(duplicate_username.status(), StatusCode::CONFLICT);
        assert_eq!(user::Entity::find().all(&*state.db).await.unwrap().len(), 1);

        let login = app
            .clone()
            .oneshot(
                Request::builder()
                    .method(Method::POST)
                    .uri("/auth/token")
                    .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
                    .body(Body::from("username=alice&password=test-password"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(login.status(), StatusCode::OK);
        let token: Value =
            serde_json::from_slice(&to_bytes(login.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(token["token_type"], "bearer");

        let current = app
            .oneshot(
                Request::builder()
                    .uri("/users/me")
                    .header("X-Api-Key", "test-api-key")
                    .header(
                        header::AUTHORIZATION,
                        format!("Bearer {}", token["access_token"].as_str().unwrap()),
                    )
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(current.status(), StatusCode::OK);
        let current: Value =
            serde_json::from_slice(&to_bytes(current.into_body(), usize::MAX).await.unwrap())
                .unwrap();
        assert_eq!(current["id"], created["id"]);
        assert_eq!(current["uid"], created["uid"]);
        assert_eq!(current["locale"], "ja-JP");
        assert_eq!(current["nickname"], "Alice");
        assert!(current.get("password").is_none());
        assert!(current.get("hashed_password").is_none());
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
