use crate::entities::item::{ActiveModel, Column, Entity};
use crate::models::account::AccountAccess;
use crate::schemas::item::{CreateItem, Item, UpdateItem};
use axum::http::StatusCode;
use sea_orm::{ActiveModelTrait, ColumnTrait, DatabaseConnection, EntityTrait, QueryFilter, Set};
use std::sync::Arc;
use uuid::Uuid;

/// Operates only inside an account resolved from live membership by the caller.
pub struct ItemService {
    db: Arc<DatabaseConnection>,
    access: AccountAccess,
}

impl ItemService {
    pub fn new(db: Arc<DatabaseConnection>, access: AccountAccess) -> Self {
        Self { db, access }
    }

    pub async fn find_all(&self) -> Result<Vec<Item>, StatusCode> {
        let items = Entity::find()
            .filter(Column::AccountId.eq(self.access.account_id.0))
            .all(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        Ok(items.into_iter().map(Item::from).collect())
    }

    pub async fn find_by_id(&self, id: Uuid) -> Result<Option<Item>, StatusCode> {
        let item = Entity::find_by_id(id)
            .filter(Column::AccountId.eq(self.access.account_id.0))
            .one(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        Ok(item.map(Item::from))
    }

    pub async fn create(&self, new: CreateItem) -> Result<Item, StatusCode> {
        let active_model = ActiveModel {
            id: Set(Uuid::now_v7()),
            title: Set(Some(new.title)),
            description: Set(new.description),
            description2: Set(new.description2),
            config: Set(new.config),
            account_id: Set(self.access.account_id.0),
            owner_id: Set(self.access.user_id.0),
            created_at: Set(chrono::Utc::now().into()),
            updated_at: Set(None),
        };
        let model = active_model
            .insert(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        Ok(Item::from(model))
    }

    pub async fn update(&self, id: Uuid, update: UpdateItem) -> Result<Option<Item>, StatusCode> {
        // The account predicate is part of the UPDATE, not just a preceding read.
        // Creator, account and creation time are deliberately absent from SET.
        let changes = ActiveModel {
            title: Set(Some(update.title)),
            description: Set(update.description),
            description2: Set(update.description2),
            config: Set(update.config),
            updated_at: Set(Some(chrono::Utc::now().into())),
            ..Default::default()
        };
        let updated = Entity::update_many()
            .set(changes)
            .filter(Column::Id.eq(id))
            .filter(Column::AccountId.eq(self.access.account_id.0))
            .exec_with_returning(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        Ok(updated.into_iter().next().map(Item::from))
    }

    pub async fn delete(&self, id: Uuid) -> Result<bool, StatusCode> {
        let result = Entity::delete_many()
            .filter(Column::Id.eq(id))
            .filter(Column::AccountId.eq(self.access.account_id.0))
            .exec(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        Ok(result.rows_affected > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AppState;
    use crate::models::account::MemberRole;
    use crate::models::account_repository::AccountRepository;
    use crate::models::shared::AccountId;
    use crate::models::user::{User, UserId, UserWrite};
    use crate::repositories::orm::account::SeaOrmAccountRepository;
    use crate::services::auth::AuthService;
    use axum::body::{Body, to_bytes};
    use axum::http::Request;
    use chrono::Utc;
    use serde_json::{Value, json};
    use tower::ServiceExt;

    async fn register(repo: &SeaOrmAccountRepository, username: &str) -> User {
        repo.register_user(&UserWrite {
            id: UserId(Uuid::now_v7()),
            email: Some(format!("{username}@example.com")),
            nickname: None,
            username: Some(username.into()),
            hashed_password: None,
            is_active: Some(true),
            locale: Default::default(),
            is_superuser: Some(false),
            created_at: Utc::now(),
            updated_at: None,
        })
        .await
        .unwrap()
    }

    async fn fixture() -> (ItemService, User) {
        let db = crate::test_support::database().await;
        let repo = SeaOrmAccountRepository::new(db.clone());
        let owner = register(&repo, "owner").await;
        let access = repo.resolve_account(owner.id.clone(), None).await.unwrap();
        (ItemService::new(db, access), owner)
    }

    fn create_item() -> CreateItem {
        CreateItem {
            title: "First item".into(),
            description: None,
            description2: Some("Secondary description".into()),
            config: json!({"enabled": true, "count": 2}),
        }
    }

    #[tokio::test]
    async fn create_makes_all_fields_retrievable_with_server_metadata() {
        let (service, owner) = fixture().await;
        let before_create = Utc::now();
        let created = service.create(create_item()).await.unwrap();
        let retrieved = service.find_by_id(created.id).await.unwrap().unwrap();
        assert_eq!(retrieved.id.get_version_num(), 7);
        assert_eq!(retrieved.title, "First item");
        assert_eq!(retrieved.description, None);
        assert_eq!(
            retrieved.description2.as_deref(),
            Some("Secondary description")
        );
        assert_eq!(retrieved.config, json!({"enabled": true, "count": 2}));
        assert_eq!(retrieved.owner_id, owner.id.0);
        assert_eq!(retrieved.account_id, service.access.account_id.0);
        assert!(retrieved.created_at >= before_create);
        assert!(retrieved.created_at <= Utc::now());
        assert_eq!(retrieved.updated_at, None);
    }

    #[tokio::test]
    async fn update_preserves_scope_and_creator_and_clears_optional_fields() {
        let (service, _) = fixture().await;
        let created = service.create(create_item()).await.unwrap();
        let before_update = Utc::now();
        let updated = service
            .update(
                created.id,
                UpdateItem {
                    title: "After".into(),
                    description: None,
                    description2: None,
                    config: json!({"enabled": false}),
                },
            )
            .await
            .unwrap()
            .unwrap();
        assert_eq!(updated.id, created.id);
        assert_eq!(updated.owner_id, created.owner_id);
        assert_eq!(updated.account_id, created.account_id);
        assert_eq!(updated.created_at, created.created_at);
        assert_eq!(updated.description2, None);
        assert_eq!(updated.config, json!({"enabled": false}));
        assert!(updated.updated_at.unwrap() >= before_update);
    }

    fn request(
        method: &str,
        uri: &str,
        body: Value,
        token: &str,
        account: Option<AccountId>,
    ) -> Request<Body> {
        let mut request = Request::builder()
            .method(method)
            .uri(uri)
            .header("X-Api-Key", "test-api-key")
            .header("Authorization", format!("Bearer {token}"))
            .header("content-type", "application/json");
        if let Some(account) = account {
            request = request.header("X-Account-Id", account.0.to_string());
        }
        request.body(Body::from(body.to_string())).unwrap()
    }

    fn state(db: Arc<DatabaseConnection>) -> Arc<AppState> {
        Arc::new(AppState {
            db,
            http: reqwest::Client::new(),
            cache: None,
            auth: Arc::new(AuthService::new(
                "test-api-key".into(),
                "test-jwt-secret-with-at-least-32-characters".into(),
                1,
            )),
        })
    }

    async fn response_item(response: axum::response::Response) -> Item {
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[tokio::test]
    async fn http_crud_uses_writable_payloads_and_preserves_all_fields() {
        let (service, owner) = fixture().await;
        let state = state(service.db.clone());
        let token = state.auth.create_access_token(owner.id.0).unwrap();
        let app = crate::routes::item::item_routes().with_state(state);
        let payload = json!({
            "title": "Created over HTTP", "description": null,
            "description2": "Keep this description", "config": {"nested": {"enabled": true}}
        });
        let mut unauthenticated = request("POST", "/items", payload.clone(), &token, None);
        unauthenticated.headers_mut().remove("authorization");
        assert_eq!(
            app.clone().oneshot(unauthenticated).await.unwrap().status(),
            StatusCode::UNAUTHORIZED
        );
        for field in ["id", "owner_id", "account_id"] {
            let mut forged = payload.clone();
            forged[field] = json!(Uuid::now_v7());
            let response = app
                .clone()
                .oneshot(request("POST", "/items", forged, &token, None))
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }
        let response = app
            .clone()
            .oneshot(request("POST", "/items", payload, &token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::CREATED);
        let created = response_item(response).await;
        assert_eq!(created.owner_id, owner.id.0);
        assert_eq!(created.account_id, service.access.account_id.0);
        assert_eq!(
            created.description2.as_deref(),
            Some("Keep this description")
        );
        let uri = format!("/items/{}", created.id);
        let replacement = json!({"title": "Replaced", "config": {"nested": {"enabled": false}}});
        let response = app
            .clone()
            .oneshot(request("PUT", &uri, replacement.clone(), &token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let updated = response_item(response).await;
        assert_eq!(updated.created_at, created.created_at);
        assert_eq!(updated.owner_id, created.owner_id);
        assert_eq!(updated.account_id, created.account_id);
        assert_eq!(updated.description2, None);
        let response = app
            .clone()
            .oneshot(request("GET", &uri, json!(null), &token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_item(response).await.config, updated.config);
        let response = app
            .clone()
            .oneshot(request("GET", "/items", json!(null), &token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        let items: Vec<Item> = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(items.len(), 1);
        let response = app
            .clone()
            .oneshot(request("DELETE", &uri, json!(null), &token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NO_CONTENT);
        for (method, body) in [
            ("GET", json!(null)),
            ("PUT", replacement),
            ("DELETE", json!(null)),
        ] {
            let response = app
                .clone()
                .oneshot(request(method, &uri, body, &token, None))
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::NOT_FOUND);
        }
    }

    #[tokio::test]
    async fn workspace_members_share_items_but_other_accounts_and_revoked_members_cannot() {
        let db = crate::test_support::database().await;
        let repo = SeaOrmAccountRepository::new(db.clone());
        let alice = register(&repo, "alice").await;
        let bob = register(&repo, "bob").await;
        let alice_personal = repo.resolve_account(alice.id.clone(), None).await.unwrap();
        let tenant = repo
            .create_tenant(alice.id.clone(), "Company")
            .await
            .unwrap();
        let first = repo
            .create_workspace(alice.id.clone(), tenant.id, "First")
            .await
            .unwrap();
        let second = repo
            .create_workspace(alice.id.clone(), tenant.id, "Second")
            .await
            .unwrap();
        repo.put_tenant_member(
            alice.id.clone(),
            tenant.id,
            bob.id.clone(),
            MemberRole::Admin,
        )
        .await
        .unwrap();
        repo.put_account_member(
            alice.id.clone(),
            first.id,
            bob.id.clone(),
            MemberRole::Member,
        )
        .await
        .unwrap();
        let state = state(db);
        let alice_token = state.auth.create_access_token(alice.id.0).unwrap();
        let bob_token = state.auth.create_access_token(bob.id.0).unwrap();
        let app = crate::routes::item::item_routes().with_state(state);
        let payload = json!({"title": "Shared", "config": {"version": 1}});
        let response = app
            .clone()
            .oneshot(request(
                "POST",
                "/items",
                payload.clone(),
                &alice_token,
                Some(first.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::CREATED);
        let item = response_item(response).await;
        let uri = format!("/items/{}", item.id);
        let response = app
            .clone()
            .oneshot(request(
                "GET",
                &uri,
                json!(null),
                &bob_token,
                Some(first.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let response = app
            .clone()
            .oneshot(request(
                "PUT",
                &uri,
                json!({"title": "Edited", "config": {"version": 2}}),
                &bob_token,
                Some(first.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_item(response).await.owner_id, alice.id.0);

        // Tenant administration does not imply membership of every workspace.
        let response = app
            .clone()
            .oneshot(request(
                "GET",
                &uri,
                json!(null),
                &bob_token,
                Some(second.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        let response = app
            .clone()
            .oneshot(request(
                "GET",
                "/items",
                json!(null),
                &bob_token,
                Some(alice_personal.account_id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        for (method, body) in [
            ("GET", json!(null)),
            ("PUT", payload),
            ("DELETE", json!(null)),
        ] {
            let response = app
                .clone()
                .oneshot(request(method, &uri, body, &alice_token, Some(second.id)))
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::NOT_FOUND);
        }
        let response = app
            .clone()
            .oneshot(request("GET", &uri, json!(null), &bob_token, None))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        let response = app
            .clone()
            .oneshot(request(
                "GET",
                "/items",
                json!(null),
                &alice_token,
                Some(second.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        assert_eq!(serde_json::from_slice::<Value>(&body).unwrap(), json!([]));
        repo.remove_account_member(alice.id.clone(), first.id, bob.id.clone())
            .await
            .unwrap();
        let response = app
            .oneshot(request(
                "GET",
                &uri,
                json!(null),
                &bob_token,
                Some(first.id),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
    }
}
