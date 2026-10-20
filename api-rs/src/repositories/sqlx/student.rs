use super::map_error;
use crate::models::student::{NewStudent, Student, StudentRepository};
use crate::repositories::RepositoryError;
use anyhow::Result;
use async_trait::async_trait;
use sqlx::{FromRow, PgPool};

pub struct SqlxStudentRepository {
    pool: PgPool,
}

impl SqlxStudentRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[derive(FromRow)]
struct StudentRow {
    id: i32,
    name: String,
    age: i32,
}

impl From<StudentRow> for Student {
    fn from(row: StudentRow) -> Self {
        Self {
            id: row.id,
            name: row.name,
            age: row.age,
        }
    }
}

#[async_trait]
impl StudentRepository for SqlxStudentRepository {
    async fn find_all(&self) -> Result<Vec<Student>> {
        sqlx::query_as::<_, StudentRow>("SELECT id, name, age FROM public.student ORDER BY id ASC")
            .fetch_all(&self.pool)
            .await
            .map(|students| students.into_iter().map(Student::from).collect())
            .map_err(map_error)
    }

    async fn create(&self, student: &NewStudent) -> Result<Student> {
        sqlx::query_as::<_, StudentRow>(
            "INSERT INTO public.student (name, age) VALUES ($1, $2) RETURNING id, name, age",
        )
        .bind(&student.name)
        .bind(student.age)
        .fetch_one(&self.pool)
        .await
        .map(Student::from)
        .map_err(map_error)
    }

    async fn find_by_id(&self, id: i32) -> Result<Option<Student>> {
        sqlx::query_as::<_, StudentRow>("SELECT id, name, age FROM public.student WHERE id = $1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map(|student| student.map(Student::from))
            .map_err(map_error)
    }

    async fn update(&self, student: &Student) -> Result<Student> {
        sqlx::query_as::<_, StudentRow>(
            "UPDATE public.student SET name = $1, age = $2 WHERE id = $3 RETURNING id, name, age",
        )
        .bind(&student.name)
        .bind(student.age)
        .bind(student.id)
        .fetch_optional(&self.pool)
        .await
        .map_err(map_error)?
        .map(Student::from)
        .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))
    }

    async fn delete_by_id(&self, id: i32) -> Result<()> {
        let result = sqlx::query("DELETE FROM public.student WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(map_error)?;
        if result.rows_affected() == 0 {
            Err(RepositoryError::NotFound.into())
        } else {
            Ok(())
        }
    }
}
