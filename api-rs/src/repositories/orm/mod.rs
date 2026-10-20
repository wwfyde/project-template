pub mod student;
pub mod todo;
pub mod user;

pub use student::SeaOrmStudentRepository;
pub use todo::SeaOrmTodoRepository;
pub use user::SeaOrmUserRepository;

use super::RepositoryError;

fn map_error(error: sea_orm::DbErr) -> anyhow::Error {
    if matches!(
        error,
        sea_orm::DbErr::RecordNotFound(_) | sea_orm::DbErr::RecordNotUpdated
    ) {
        anyhow::Error::new(error).context(RepositoryError::NotFound)
    } else if matches!(
        error.sql_err(),
        Some(sea_orm::SqlErr::UniqueConstraintViolation(_))
    ) {
        anyhow::Error::new(error).context(RepositoryError::Conflict)
    } else {
        anyhow::Error::new(error)
    }
}
