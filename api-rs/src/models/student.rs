use anyhow::Result;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Student {
    pub id: i32,
    pub name: String,
    pub age: i32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct NewStudent {
    pub name: String,
    pub age: i32,
}

#[async_trait]
pub trait StudentRepository: Send + Sync {
    async fn find_all(&self) -> Result<Vec<Student>>;
    async fn create(&self, student: &NewStudent) -> Result<Student>;
    async fn find_by_id(&self, id: i32) -> Result<Option<Student>>;
    async fn update(&self, student: &Student) -> Result<Student>;
    async fn delete_by_id(&self, id: i32) -> Result<()>;
}
