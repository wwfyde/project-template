use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Todo {
    pub id: Uuid,
    pub title: String,
    pub completed: Option<bool>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[async_trait::async_trait]
pub trait TodoRepository: Send + Sync {
    async fn find_all(&self) -> Result<Vec<Todo>>;
    async fn create(&self, todo: &Todo) -> Result<Todo>;
    async fn find_by_id(&self, id: Uuid) -> Result<Option<Todo>>;
    async fn update(&self, todo: &Todo) -> Result<Todo>;
    async fn delete_by_id(&self, id: Uuid) -> Result<()>;
}
