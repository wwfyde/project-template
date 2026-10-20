use super::map_error;
use crate::models::todo::{Todo, TodoRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use chrono::{DateTime, Utc};
use sqlx::{FromRow, PgPool};
use uuid::Uuid;

#[derive(FromRow)]
struct TodoRow {
    id: Uuid,
    title: String,
    completed: Option<bool>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

impl From<TodoRow> for Todo {
    fn from(row: TodoRow) -> Self {
        Self {
            id: row.id,
            title: row.title,
            completed: row.completed,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }
}

pub struct SqlxTodoRepository {
    pool: PgPool,
}

impl SqlxTodoRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait::async_trait]
impl TodoRepository for SqlxTodoRepository {
    async fn find_all(&self) -> Result<Vec<Todo>> {
        let rows = sqlx::query_as::<_, TodoRow>(
            "SELECT id, title, completed, created_at, updated_at FROM public.todo ORDER BY id ASC",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(map_error)?;
        Ok(rows.into_iter().map(Todo::from).collect())
    }

    async fn create(&self, todo: &Todo) -> Result<Todo> {
        let row = sqlx::query_as::<_, TodoRow>(
            "INSERT INTO public.todo (id, title, completed, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5)
             RETURNING id, title, completed, created_at, updated_at",
        )
        .bind(todo.id)
        .bind(&todo.title)
        .bind(todo.completed)
        .bind(todo.created_at)
        .bind(todo.updated_at)
        .fetch_one(&self.pool)
        .await
        .map_err(map_error)?;
        Ok(row.into())
    }

    async fn find_by_id(&self, id: Uuid) -> Result<Option<Todo>> {
        let row = sqlx::query_as::<_, TodoRow>(
            "SELECT id, title, completed, created_at, updated_at FROM public.todo WHERE id = $1",
        )
        .bind(id)
        .fetch_optional(&self.pool)
        .await
        .map_err(map_error)?;
        Ok(row.map(Todo::from))
    }

    async fn update(&self, todo: &Todo) -> Result<Todo> {
        let row = sqlx::query_as::<_, TodoRow>(
            "UPDATE public.todo SET title = $2, completed = $3, updated_at = $4 WHERE id = $1
             RETURNING id, title, completed, created_at, updated_at",
        )
        .bind(todo.id)
        .bind(&todo.title)
        .bind(todo.completed)
        .bind(todo.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(map_error)?
        .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        Ok(row.into())
    }

    async fn delete_by_id(&self, id: Uuid) -> Result<()> {
        let result = sqlx::query("DELETE FROM public.todo WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(map_error)?;
        if result.rows_affected() == 0 {
            return Err(RepositoryError::NotFound.into());
        }
        Ok(())
    }
}
