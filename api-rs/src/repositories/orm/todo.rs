use super::map_error;
use crate::entities::todo::{ActiveModel, COLUMN, Entity, Model};
use crate::models::todo::{Todo, TodoRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use sea_orm::{ActiveModelTrait, DatabaseConnection, EntityTrait, QueryOrder, Set, Unchanged};
use std::sync::Arc;
use uuid::Uuid;

impl From<Model> for Todo {
    fn from(model: Model) -> Self {
        Self {
            id: model.id,
            title: model.title,
            completed: model.completed,
            created_at: model.created_at.into(),
            updated_at: model.updated_at.into(),
        }
    }
}

pub struct SeaOrmTodoRepository {
    db: Arc<DatabaseConnection>,
}

impl SeaOrmTodoRepository {
    pub fn new(db: Arc<DatabaseConnection>) -> Self {
        Self { db }
    }
}

#[async_trait::async_trait]
impl TodoRepository for SeaOrmTodoRepository {
    async fn find_all(&self) -> Result<Vec<Todo>> {
        let todos = Entity::find()
            .order_by_asc(COLUMN.id)
            .all(self.db.as_ref())
            .await
            .map_err(map_error)?;
        Ok(todos.into_iter().map(Todo::from).collect())
    }

    async fn create(&self, todo: &Todo) -> Result<Todo> {
        let model = ActiveModel {
            id: Set(todo.id),
            title: Set(todo.title.clone()),
            completed: Set(todo.completed),
            created_at: Set(todo.created_at.into()),
            updated_at: Set(todo.updated_at.into()),
        }
        .insert(self.db.as_ref())
        .await
        .map_err(map_error)?;
        Ok(model.into())
    }

    async fn find_by_id(&self, id: Uuid) -> Result<Option<Todo>> {
        let todo = Entity::find_by_id(id)
            .one(self.db.as_ref())
            .await
            .map_err(map_error)?;
        Ok(todo.map(Todo::from))
    }

    async fn update(&self, todo: &Todo) -> Result<Todo> {
        let model = ActiveModel {
            id: Unchanged(todo.id),
            title: Set(todo.title.clone()),
            completed: Set(todo.completed),
            updated_at: Set(todo.updated_at.into()),
            ..Default::default()
        }
        .update(self.db.as_ref())
        .await
        .map_err(map_error)?;
        Ok(model.into())
    }

    async fn delete_by_id(&self, id: Uuid) -> Result<()> {
        let result = Entity::delete_by_id(id)
            .exec(self.db.as_ref())
            .await
            .map_err(map_error)?;
        if result.rows_affected == 0 {
            return Err(RepositoryError::NotFound.into());
        }
        Ok(())
    }
}
