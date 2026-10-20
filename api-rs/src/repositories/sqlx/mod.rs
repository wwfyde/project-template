pub mod student;
pub mod todo;
pub mod user;

pub use student::SqlxStudentRepository;
pub use todo::SqlxTodoRepository;
pub use user::SqlxUserRepository;

use super::RepositoryError;

fn map_error(error: ::sqlx::Error) -> anyhow::Error {
    if matches!(error, ::sqlx::Error::RowNotFound) {
        anyhow::Error::new(error).context(RepositoryError::NotFound)
    } else if error
        .as_database_error()
        .is_some_and(|error| error.is_unique_violation())
    {
        anyhow::Error::new(error).context(RepositoryError::Conflict)
    } else {
        anyhow::Error::new(error)
    }
}
