use super::*;
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode};
use sea_orm::Database;
use tower::ServiceExt;

async fn app() -> Router {
    build_app(Arc::new(AppState {
        db: Arc::new(Database::connect("sqlite::memory:").await.unwrap()),
        http: reqwest::Client::new(),
        cache: None,
        auth: Arc::new(AuthService::new(
            "test-key".into(),
            "test-jwt-secret-with-at-least-32-characters".into(),
            1,
        )),
    }))
}

#[tokio::test]
async fn user_repository_and_current_user_round_trip() {
    use crate::models::user::{UserId, UserRepository, UserWrite};
    use crate::repositories::RepositoryError;
    use crate::repositories::orm::SeaOrmUserRepository;
    use sea_orm::{ConnectOptions, ConnectionTrait};
    use uuid::Uuid;

    let mut options = ConnectOptions::new("sqlite::memory:");
    options.max_connections(1);
    let db = Arc::new(Database::connect(options).await.unwrap());
    db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
        .await
        .unwrap();
    db.execute(&crate::repositories::orm::user::user_table_for_tests(
        db.get_database_backend(),
    ))
    .await
    .unwrap();
    let repo = SeaOrmUserRepository::new(db.clone());
    let original = UserWrite {
        id: UserId(Uuid::now_v7()),
        email: Some("alice@example.com".into()),
        nickname: Some("Alice".into()),
        username: Some("alice".into()),
        hashed_password: Some(bcrypt::hash("test-password", 4).unwrap()),
        is_active: Some(true),
        locale: crate::models::Locale::JaJp,
        is_superuser: Some(false),
        created_at: chrono::Utc::now(),
        updated_at: None,
    };
    let saved = repo.insert(&original).await.unwrap();
    assert_eq!(
        repo.find_by_email("alice@example.com").await.unwrap(),
        Some(saved.clone())
    );
    assert_eq!(
        repo.find_by_id(saved.id.clone()).await.unwrap(),
        Some(saved.clone())
    );
    assert_eq!(repo.find_all().await.unwrap(), vec![saved.clone()]);

    let auth = Arc::new(AuthService::new(
        "test-key".into(),
        "test-jwt-secret-with-at-least-32-characters".into(),
        1,
    ));
    let app = build_app(Arc::new(AppState {
        db,
        http: reqwest::Client::new(),
        cache: None,
        auth,
    }));
    let login = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/auth/token")
                .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
                .body(Body::from("username=alice&password=test-password"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(login.status(), StatusCode::OK);
    let token: Value =
        serde_json::from_slice(&to_bytes(login.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(token["expires_in"], 86_400);
    let current = app
        .oneshot(
            Request::builder()
                .uri("/api/users/me")
                .header("x-api-key", "test-key")
                .header(
                    AUTHORIZATION,
                    format!("Bearer {}", token["access_token"].as_str().unwrap()),
                )
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(current.status(), StatusCode::OK);
    let current: Value =
        serde_json::from_slice(&to_bytes(current.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(current["id"], saved.id.0.to_string());
    assert_eq!(current["username"], "alice");
    assert_eq!(current["uid"], saved.uid.0);
    assert_eq!(current["nickname"], "Alice");
    assert_eq!(current["locale"], "ja-JP");
    assert!(current.get("hashed_password").is_none());

    let mut update = UserWrite::from(&saved);
    update.email = Some("updated@example.com".into());
    update.created_at -= chrono::Duration::days(1);
    update.updated_at = Some(chrono::Utc::now());
    let updated = repo.update(&update).await.unwrap();
    assert_eq!(updated.created_at, saved.created_at);
    assert_eq!(updated.email, update.email);
    assert_eq!(updated.updated_at, update.updated_at);
    repo.delete_by_id(saved.id.clone()).await.unwrap();
    assert!(repo.find_by_id(saved.id.clone()).await.unwrap().is_none());
    for error in [
        repo.update(&UserWrite::from(&saved)).await.unwrap_err(),
        repo.delete_by_id(saved.id).await.unwrap_err(),
    ] {
        assert!(matches!(
            error.downcast_ref::<RepositoryError>(),
            Some(RepositoryError::NotFound)
        ));
    }
}

#[tokio::test]
async fn health_and_openapi_are_served_without_configuration_or_external_services() {
    let app = app().await;
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap()["status"],
        "ok"
    );

    let response = app
        .oneshot(
            Request::builder()
                .uri("/api-docs/openapi.json")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let doc: Value = serde_json::from_slice(&body).unwrap();
    for path in [
        "/api/users",
        "/api/users/me",
        "/api/users/{id}",
        "/api/items",
        "/api/items/{id}",
        "/api/auth/token",
    ] {
        assert!(doc["paths"].get(path).is_some(), "missing {path}");
    }
}

#[tokio::test]
async fn cors_preflight_allows_required_authentication_headers() {
    let response = app()
        .await
        .oneshot(
            Request::builder()
                .method("OPTIONS")
                .uri("/api/users")
                .header("origin", "http://localhost:5173")
                .header("access-control-request-method", "GET")
                .header(
                    "access-control-request-headers",
                    "authorization,x-api-key,x-account-id,content-type",
                )
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let allowed = response.headers()["access-control-allow-headers"]
        .to_str()
        .unwrap();
    for header in ["authorization", "x-api-key", "x-account-id", "content-type"] {
        assert!(
            allowed.split(',').any(|value| value.trim() == header),
            "missing {header}"
        );
    }
}
