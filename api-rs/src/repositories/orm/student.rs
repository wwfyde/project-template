use super::map_error;
use crate::entities::student::{ActiveModel, COLUMN, Entity, Model};
use crate::models::student::{NewStudent, Student, StudentRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use async_trait::async_trait;
use sea_orm::{
    ActiveModelTrait, DatabaseConnection, EntityTrait, NotSet, QueryOrder, Set, Unchanged,
};
use std::sync::Arc;

pub struct SeaOrmStudentRepository {
    db: Arc<DatabaseConnection>,
}

impl SeaOrmStudentRepository {
    pub fn new(db: Arc<DatabaseConnection>) -> Self {
        Self { db }
    }
}

#[async_trait]
impl StudentRepository for SeaOrmStudentRepository {
    async fn find_all(&self) -> Result<Vec<Student>> {
        Entity::find()
            .order_by_asc(COLUMN.id)
            .all(self.db.as_ref())
            .await
            .map(|students| students.into_iter().map(Student::from).collect())
            .map_err(map_error)
    }

    async fn create(&self, student: &NewStudent) -> Result<Student> {
        ActiveModel {
            id: NotSet,
            name: Set(student.name.clone()),
            age: Set(student.age),
        }
        .insert(self.db.as_ref())
        .await
        .map(Student::from)
        .map_err(map_error)
    }

    async fn find_by_id(&self, id: i32) -> Result<Option<Student>> {
        Entity::find_by_id(id)
            .one(self.db.as_ref())
            .await
            .map(|student| student.map(Student::from))
            .map_err(map_error)
    }

    async fn update(&self, student: &Student) -> Result<Student> {
        ActiveModel {
            id: Unchanged(student.id),
            name: Set(student.name.clone()),
            age: Set(student.age),
        }
        .update(self.db.as_ref())
        .await
        .map(Student::from)
        .map_err(map_error)
    }

    async fn delete_by_id(&self, id: i32) -> Result<()> {
        let result = Entity::delete_by_id(id)
            .exec(self.db.as_ref())
            .await
            .map_err(map_error)?;
        if result.rows_affected == 0 {
            Err(RepositoryError::NotFound.into())
        } else {
            Ok(())
        }
    }
}

impl From<Model> for Student {
    fn from(model: Model) -> Self {
        Self {
            id: model.id,
            name: model.name,
            age: model.age,
        }
    }
}
