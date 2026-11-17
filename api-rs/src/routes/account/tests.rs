use super::*;

use axum::body::{Body, to_bytes};
use axum::http::{Method, Request, StatusCode};
use sea_orm::{EntityTrait, PaginatorTrait};
use serde_json::{Value, json};
use tower::ServiceExt;
use utoipa::OpenApi;
use uuid::Uuid;

use crate::entities::{account, account_member, tenant, tenant_member};
use crate::services::auth::AuthService;

struct App {
    router: Router,
    state: Arc<AppState>,
}

impl App {
    async fn new() -> Self {
        let state = Arc::new(AppState {
            db: crate::test_support::database().await,
            http: reqwest::Client::new(),
            cache: None,
            auth: Arc::new(AuthService::new(
                "account-test-key".into(),
                "account-test-jwt-secret-at-least-32-characters".into(),
                1,
            )),
        });
        Self {
            router: crate::routes::all_routes().with_state(state.clone()),
            state,
        }
    }

    async fn call(
        &self,
        method: Method,
        path: &str,
        actor: Option<Uuid>,
        account: Option<Uuid>,
        body: Value,
    ) -> (StatusCode, Value) {
        let mut request = Request::builder()
            .method(method)
            .uri(path)
            .header("X-Api-Key", "account-test-key")
            .header("Content-Type", "application/json");
        if let Some(actor) = actor {
            let token = self.state.auth.create_access_token(actor).unwrap();
            request = request.header("Authorization", format!("Bearer {token}"));
        }
        if let Some(account) = account {
            request = request.header("X-Account-Id", account.to_string());
        }
        let response = self
            .router
            .clone()
            .oneshot(
                request
                    .body(if body.is_null() {
                        Body::empty()
                    } else {
                        Body::from(body.to_string())
                    })
                    .unwrap(),
            )
            .await
            .unwrap();
        let status = response.status();
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        (status, serde_json::from_slice(&body).unwrap_or(Value::Null))
    }

    async fn register(&self, name: &str) -> Uuid {
        let (status, body) = self.call(Method::POST, "/api/users", None, None, json!({
            "username": name, "password": "account-test-password", "email": format!("{name}@example.com")
        })).await;
        assert_eq!(status, StatusCode::CREATED);
        id(&body, "id")
    }
}

fn id(value: &Value, field: &str) -> Uuid {
    Uuid::parse_str(value[field].as_str().unwrap()).unwrap()
}

#[tokio::test]
async fn registration_provisions_personal_billing_and_resource_memberships() {
    let app = App::new().await;
    let alice = app.register("alice").await;
    let (status, accounts) = app
        .call(Method::GET, "/api/accounts", Some(alice), None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::OK);
    let accounts = accounts.as_array().unwrap();
    assert_eq!(accounts.len(), 1);
    let personal = &accounts[0];
    assert_eq!(personal["kind"], "personal");
    assert_eq!(personal["personal_user_id"], json!(alice));
    let (status, current) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(alice),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(current["account_id"], personal["id"]);
    assert_eq!(current["tenant_id"], personal["tenant_id"]);
    assert_eq!(current["role"], "owner");
    assert_eq!(
        tenant::Entity::find().count(&*app.state.db).await.unwrap(),
        1
    );
    assert_eq!(
        account::Entity::find().count(&*app.state.db).await.unwrap(),
        1
    );
    assert_eq!(
        tenant_member::Entity::find()
            .count(&*app.state.db)
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        account_member::Entity::find()
            .count(&*app.state.db)
            .await
            .unwrap(),
        1
    );

    let bob = app.register("bob").await;
    let (status, _) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(bob),
            Some(id(personal, "id")),
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, users) = app
        .call(Method::GET, "/api/users", Some(alice), None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(users.as_array().unwrap().len(), 1);
    assert_eq!(users[0]["id"], json!(alice));
    let (status, _) = app
        .call(
            Method::GET,
            &format!("/api/users/{bob}"),
            Some(alice),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn user_can_switch_accounts_without_tenant_admin_bypassing_workspace_membership() {
    let app = App::new().await;
    let alice = app.register("alice").await;
    let bob = app.register("bob").await;
    let (status, org) = app
        .call(
            Method::POST,
            "/api/tenants",
            Some(alice),
            None,
            json!({"name": "Acme"}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(org["kind"], "organization");
    let tenant_id = id(&org, "id");
    let (status, workspace) = app
        .call(
            Method::POST,
            &format!("/api/tenants/{tenant_id}/accounts"),
            Some(alice),
            None,
            json!({"name": "Design"}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(workspace["kind"], "workspace");
    let workspace_id = id(&workspace, "id");

    let (status, _) = app
        .call(
            Method::PUT,
            &format!("/api/tenants/{tenant_id}/members/{bob}"),
            Some(alice),
            None,
            json!({"role": "admin"}),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    let (status, _) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(bob),
            Some(workspace_id),
            Value::Null,
        )
        .await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "tenant administration does not grant workspace access"
    );
    let (status, other) = app
        .call(
            Method::POST,
            &format!("/api/tenants/{tenant_id}/accounts"),
            Some(bob),
            None,
            json!({"name": "Engineering"}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(
        other["tenant_id"], workspace["tenant_id"],
        "billing attribution is shared"
    );
    let (status, _) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(alice),
            Some(id(&other, "id")),
            Value::Null,
        )
        .await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "tenant owner also needs workspace membership"
    );

    let (status, _) = app
        .call(
            Method::PUT,
            &format!("/api/accounts/{workspace_id}/members/{bob}"),
            Some(alice),
            None,
            json!({"role": "member"}),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    let (status, accounts) = app
        .call(Method::GET, "/api/accounts", Some(bob), None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(accounts.as_array().unwrap().len(), 3);
    let (status, selected) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(bob),
            Some(workspace_id),
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(selected["tenant_id"], json!(tenant_id));
    assert_eq!(selected["role"], "member");
    let (status, users) = app
        .call(
            Method::GET,
            "/api/users",
            Some(bob),
            Some(workspace_id),
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(users.as_array().unwrap().len(), 2);

    let (status, _) = app
        .call(
            Method::PUT,
            &format!("/api/accounts/{workspace_id}/members/{bob}"),
            Some(bob),
            None,
            json!({"role": "owner"}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, _) = app
        .call(
            Method::DELETE,
            &format!("/api/accounts/{workspace_id}/members/{alice}"),
            Some(alice),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(
        status,
        StatusCode::CONFLICT,
        "the last workspace owner cannot be removed"
    );
    let (status, _) = app
        .call(
            Method::DELETE,
            &format!("/api/accounts/{workspace_id}/members/{bob}"),
            Some(alice),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    let (status, _) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(bob),
            Some(workspace_id),
            Value::Null,
        )
        .await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "revocation applies without replacing the JWT"
    );
    let (status, personal) = app
        .call(
            Method::GET,
            "/api/accounts/current",
            Some(bob),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_ne!(personal["tenant_id"], json!(tenant_id));
}

#[test]
fn openapi_exposes_account_membership_and_billing_scopes() {
    let document = serde_json::to_value(crate::routes::AllApi::openapi()).unwrap();
    let mut operations = std::collections::BTreeSet::new();
    for path in document["paths"].as_object().unwrap().values() {
        for method in ["get", "post", "put", "delete"] {
            if let Some(operation) = path[method]["operationId"].as_str() {
                assert!(
                    operations.insert(operation),
                    "duplicate operation ID {operation}"
                );
            }
        }
    }
    for path in [
        "/accounts",
        "/accounts/current",
        "/accounts/{account_id}/members/{user_id}",
        "/tenants",
        "/tenants/{tenant_id}/accounts",
        "/tenants/{tenant_id}/members/{user_id}",
    ] {
        assert!(document["paths"].get(path).is_some(), "missing {path}");
    }
    for name in [
        "TenantResponse",
        "AccountResponse",
        "AccountContextResponse",
        "TenantKind",
        "AccountKind",
        "MemberRole",
    ] {
        assert!(
            document["components"]["schemas"].get(name).is_some(),
            "missing {name}"
        );
    }
    assert_eq!(
        document["paths"]["/accounts/current"]["get"]["security"],
        json!([{"api_key": [], "jwt_auth": []}])
    );
    let parameters = document["paths"]["/accounts/current"]["get"]["parameters"]
        .as_array()
        .unwrap();
    assert!(
        parameters
            .iter()
            .any(|p| p["name"] == "X-Account-Id" && p["in"] == "header")
    );
}
