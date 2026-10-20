use crate::models::student::{NewStudent, Student, StudentRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use async_trait::async_trait;
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Default)]
struct StudentState {
    students: BTreeMap<i32, Student>,
    last_id: i32,
}

#[derive(Clone, Default)]
pub struct InMemoryStudentRepository {
    data: Arc<RwLock<StudentState>>,
}

#[async_trait]
impl StudentRepository for InMemoryStudentRepository {
    async fn find_all(&self) -> Result<Vec<Student>> {
        Ok(self.data.read().await.students.values().cloned().collect())
    }

    async fn create(&self, student: &NewStudent) -> Result<Student> {
        let mut data = self.data.write().await;
        let id = data
            .last_id
            .checked_add(1)
            .ok_or(RepositoryError::InvalidInput("student ID space exhausted"))?;
        let student = Student {
            id,
            name: student.name.clone(),
            age: student.age,
        };
        data.students.insert(id, student.clone());
        data.last_id = id;
        Ok(student)
    }

    async fn find_by_id(&self, id: i32) -> Result<Option<Student>> {
        Ok(self.data.read().await.students.get(&id).cloned())
    }

    async fn update(&self, student: &Student) -> Result<Student> {
        let mut data = self.data.write().await;
        let existing = data
            .students
            .get_mut(&student.id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        *existing = student.clone();
        Ok(student.clone())
    }

    async fn delete_by_id(&self, id: i32) -> Result<()> {
        self.data
            .write()
            .await
            .students
            .remove(&id)
            .map(|_| ())
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))
    }
}
