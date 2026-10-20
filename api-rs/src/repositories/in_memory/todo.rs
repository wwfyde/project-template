use crate::models::todo::{Todo, TodoRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use async_trait::async_trait;
use std::collections::{BTreeMap, btree_map::Entry};
use std::sync::Arc;
use tokio::sync::RwLock;
use uuid::Uuid;

#[derive(Clone, Default)]
pub struct InMemoryTodoRepository {
    data: Arc<RwLock<BTreeMap<Uuid, Todo>>>,
}

#[async_trait]
impl TodoRepository for InMemoryTodoRepository {
    async fn find_all(&self) -> Result<Vec<Todo>> {
        Ok(self.data.read().await.values().cloned().collect())
    }

    async fn create(&self, todo: &Todo) -> Result<Todo> {
        let mut data = self.data.write().await;
        match data.entry(todo.id) {
            Entry::Occupied(_) => Err(RepositoryError::Conflict.into()),
            Entry::Vacant(entry) => {
                entry.insert(todo.clone());
                Ok(todo.clone())
            }
        }
    }

    async fn find_by_id(&self, id: Uuid) -> Result<Option<Todo>> {
        Ok(self.data.read().await.get(&id).cloned())
    }

    async fn update(&self, todo: &Todo) -> Result<Todo> {
        let mut data = self.data.write().await;
        let existing = data
            .get_mut(&todo.id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        let mut updated = todo.clone();
        updated.created_at = existing.created_at;
        *existing = updated.clone();
        Ok(updated)
    }

    async fn delete_by_id(&self, id: Uuid) -> Result<()> {
        self.data
            .write()
            .await
            .remove(&id)
            .map(|_| ())
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))
    }
}
