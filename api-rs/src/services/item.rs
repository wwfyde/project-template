use crate::entities::item::{ActiveModel, Entity};
use crate::schemas::item::{CreateItem, Item, UpdateItem};
use axum::http::StatusCode;
use sea_orm::{ActiveModelTrait, DatabaseConnection, EntityTrait, Set};
use std::sync::Arc;
use uuid::Uuid;

pub struct ItemService {
    db: Arc<DatabaseConnection>,
}

impl ItemService {
    pub fn new(db: Arc<DatabaseConnection>) -> Self {
        Self { db }
    }

    pub async fn find_all(&self) -> Result<Vec<Item>, StatusCode> {
        let items = Entity::find()
            .all(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

        Ok(items.into_iter().map(Item::from).collect())
    }

    pub async fn find_by_id(&self, id: Uuid) -> Result<Option<Item>, StatusCode> {
        let item = Entity::find_by_id(id)
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
            owner_id: Set(new.owner_id),
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
        let item_result = Entity::find_by_id(id)
            .one(&*self.db)
            .await
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

        if let Some(item) = item_result {
            let mut active_model: ActiveModel = item.into();

            active_model.title = Set(Some(update.title));
            active_model.description = Set(update.description);
            active_model.description2 = Set(update.description2);
            active_model.config = Set(update.config);
            active_model.owner_id = Set(update.owner_id);
            active_model.updated_at = Set(Some(chrono::Utc::now().into()));

            let updated_model = active_model
                .update(&*self.db)
                .await
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

            Ok(Some(Item::from(updated_model)))
        } else {
            Ok(None)
        }
    }

    pub async fn delete(&self, id: Uuid) -> Result<bool, StatusCode> {
        let result = Entity::delete_by_id(id)
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
    use crate::entities::{item, user};
    use crate::services::auth::AuthService;
    use axum::body::{Body, to_bytes};
    use axum::http::Request;
    use chrono::Utc;
    use sea_orm::{ConnectOptions, ConnectionTrait, Database, Schema};
    use serde_json::json;
    use tower::ServiceExt;

    async fn service_with_owner() -> (ItemService, Uuid) {
        let mut options = ConnectOptions::new("sqlite::memory:");
        options.max_connections(1);
        let db = Database::connect(options).await.unwrap();
        db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
            .await
            .unwrap();
        let schema = Schema::new(db.get_database_backend());
        db.execute(&schema.create_table_from_entity(user::Entity))
            .await
            .unwrap();
        db.execute(&schema.create_table_from_entity(item::Entity))
            .await
            .unwrap();
        let owner_id = Uuid::now_v7();
        user::ActiveModel {
            id: Set(owner_id),
            email: Set("owner@example.com".to_owned()),
            created_at: Set(Utc::now().into()),
            ..Default::default()
        }
        .insert(&db)
        .await
        .unwrap();
        (ItemService::new(Arc::new(db)), owner_id)
    }

    #[tokio::test]
    async fn create_makes_all_fields_retrievable_with_server_metadata() {
        let (service, owner_id) = service_with_owner().await;
        let before_create = Utc::now();
        let created = service
            .create(CreateItem {
                title: "First item".to_owned(),
                description: None,
                description2: Some("Secondary description".to_owned()),
                config: json!({"enabled": true, "count": 2}),
                owner_id,
            })
            .await
            .unwrap();
        let retrieved = service.find_by_id(created.id).await.unwrap().unwrap();

        assert_eq!(retrieved.id.get_version_num(), 7);
        assert_eq!(retrieved.title, "First item");
        assert_eq!(retrieved.description, None);
        assert_eq!(
            retrieved.description2.as_deref(),
            Some("Secondary description")
        );
        assert_eq!(retrieved.config, json!({"enabled": true, "count": 2}));
        assert_eq!(retrieved.owner_id, owner_id);
        assert!(retrieved.created_at >= before_create);
        assert!(retrieved.created_at <= Utc::now());
        assert_eq!(retrieved.updated_at, None);
    }

    #[tokio::test]
    async fn update_replaces_fields_clears_descriptions_and_sets_timestamp() {
        let (service, owner_id) = service_with_owner().await;
        let created = service
            .create(CreateItem {
                title: "Before".to_owned(),
                description: Some("Original description".to_owned()),
                description2: Some("Original secondary description".to_owned()),
                config: json!({"enabled": false}),
                owner_id,
            })
            .await
            .unwrap();
        let before_update = Utc::now();
        let updated = service
            .update(
                created.id,
                UpdateItem {
                    title: "After".to_owned(),
                    description: None,
                    description2: None,
                    config: json!({"enabled": true}),
                    owner_id,
                },
            )
            .await
            .unwrap()
            .unwrap();
        let retrieved = service.find_by_id(created.id).await.unwrap().unwrap();

        assert_eq!(retrieved.id, created.id);
        assert_eq!(retrieved.created_at, created.created_at);
        assert_eq!(retrieved.title, "After");
        assert_eq!(retrieved.description, None);
        assert_eq!(retrieved.description2, None);
        assert_eq!(retrieved.config, json!({"enabled": true}));
        assert_eq!(retrieved.updated_at, updated.updated_at);
        assert!(retrieved.updated_at.unwrap() >= before_update);
        assert!(retrieved.updated_at.unwrap() <= Utc::now());
    }

    fn request(method: &str, uri: &str, body: serde_json::Value) -> Request<Body> {
        Request::builder()
            .method(method)
            .uri(uri)
            .header("X-Api-Key", "test-api-key")
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    }

    async fn response_item(response: axum::response::Response) -> Item {
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[tokio::test]
    async fn http_crud_uses_writable_payloads_and_preserves_all_fields() {
        let (service, owner_id) = service_with_owner().await;
        let app = crate::routes::item::item_routes().with_state(Arc::new(AppState {
            db: service.db.clone(),
            auth: Arc::new(AuthService::new(
                "test-api-key".to_owned(),
                "test-jwt-secret".to_owned(),
                1,
            )),
        }));
        let payload = json!({
            "title": "Created over HTTP",
            "description": null,
            "description2": "Keep this description",
            "config": {"nested": {"enabled": true}},
            "owner_id": owner_id
        });
        let mut legacy_payload = payload.clone();
        legacy_payload["id"] = json!(Uuid::now_v7());
        let response = app
            .clone()
            .oneshot(request("POST", "/items", legacy_payload))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);

        let response = app
            .clone()
            .oneshot(request("POST", "/items", payload))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::CREATED);
        let created = response_item(response).await;
        assert_eq!(created.description, None);
        assert_eq!(
            created.description2.as_deref(),
            Some("Keep this description")
        );
        assert_eq!(created.config, json!({"nested": {"enabled": true}}));

        let uri = format!("/items/{}", created.id);
        let replacement = json!({
            "title": "Replaced over HTTP",
            "config": {"nested": {"enabled": false}},
            "owner_id": owner_id
        });
        let response = app
            .clone()
            .oneshot(request("PUT", &uri, replacement.clone()))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let updated = response_item(response).await;
        assert_eq!(updated.id, created.id);
        assert_eq!(updated.created_at, created.created_at);
        assert_eq!(updated.description, None);
        assert_eq!(updated.description2, None);
        assert_eq!(updated.title, "Replaced over HTTP");
        assert_eq!(updated.config, json!({"nested": {"enabled": false}}));
        assert!(updated.updated_at.is_some());

        let response = app
            .clone()
            .oneshot(request("GET", &uri, json!(null)))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_item(response).await.config, updated.config);

        let response = app
            .clone()
            .oneshot(request("GET", "/items", json!(null)))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        let items: Vec<Item> = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].id, created.id);

        let response = app
            .clone()
            .oneshot(request("DELETE", &uri, json!(null)))
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
                .oneshot(request(method, &uri, body))
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::NOT_FOUND);
        }
    }
}
