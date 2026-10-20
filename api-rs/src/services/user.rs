use crate::models::user::{User, UserId, UserRepository};
use crate::repositories::RepositoryError;
use axum::http::StatusCode;
use std::sync::Arc;

pub struct UserService {
    repo: Arc<dyn UserRepository>,
}

impl UserService {
    pub fn new(repo: Arc<dyn UserRepository>) -> Self {
        Self { repo }
    }

    pub async fn find_all(&self) -> Result<Vec<User>, StatusCode> {
        let users = self.repo.find_all().await.map_err(map_repo_error)?;
        Ok(users)
    }

    pub async fn find_by_id(&self, id: UserId) -> Result<Option<User>, StatusCode> {
        self.repo.find_by_id(id).await.map_err(map_repo_error)
    }

    pub async fn create(&self, new: User) -> Result<User, StatusCode> {
        self.repo.insert(&new).await.map_err(map_repo_error)
    }

    pub async fn update(&self, id: UserId, update: User) -> Result<Option<User>, StatusCode> {
        let mut update = update;
        update.id = id;

        match self.repo.update(&update).await {
            Ok(user) => Ok(Some(user)),
            Err(error) if is_not_found(&error) => Ok(None),
            Err(err) => Err(map_repo_error(err)),
        }
    }

    pub async fn delete(&self, id: UserId) -> Result<bool, StatusCode> {
        match self.repo.delete_by_id(id).await {
            Ok(()) => Ok(true),
            Err(error) if is_not_found(&error) => Ok(false),
            Err(err) => Err(map_repo_error(err)),
        }
    }
}

fn is_not_found(error: &anyhow::Error) -> bool {
    matches!(
        error.downcast_ref::<RepositoryError>(),
        Some(RepositoryError::NotFound)
    )
}

fn map_repo_error(error: anyhow::Error) -> StatusCode {
    match error.downcast_ref::<RepositoryError>() {
        Some(RepositoryError::NotFound) => StatusCode::NOT_FOUND,
        Some(RepositoryError::Conflict) => StatusCode::CONFLICT,
        Some(RepositoryError::InvalidInput(_)) => StatusCode::BAD_REQUEST,
        None => {
            tracing::error!(?error, "user repository error");
            StatusCode::INTERNAL_SERVER_ERROR
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::repositories::in_memory::InMemoryUserRepository;
    use chrono::Utc;
    use uuid::Uuid;

    #[test]
    fn repository_error_classification_is_backend_independent() {
        assert_eq!(
            map_repo_error(RepositoryError::NotFound.into()),
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            map_repo_error(RepositoryError::Conflict.into()),
            StatusCode::CONFLICT
        );
        assert_eq!(
            map_repo_error(RepositoryError::InvalidInput("email").into()),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            map_repo_error(anyhow::anyhow!("database host not found")),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    #[test]
    fn repository_markers_remain_classifiable_through_context() {
        for (marker, status) in [
            (RepositoryError::NotFound, StatusCode::NOT_FOUND),
            (RepositoryError::Conflict, StatusCode::CONFLICT),
            (
                RepositoryError::InvalidInput("email"),
                StatusCode::BAD_REQUEST,
            ),
        ] {
            let error = anyhow::Error::new(marker)
                .context("repository operation failed")
                .context("user operation failed");
            assert_eq!(is_not_found(&error), status == StatusCode::NOT_FOUND);
            assert_eq!(map_repo_error(error), status);
        }
    }

    #[test]
    fn repository_marker_preserves_the_original_database_error() {
        let error = anyhow::Error::new(sqlx::Error::RowNotFound)
            .context(RepositoryError::NotFound)
            .context("find user for update");

        assert!(matches!(
            error.downcast_ref::<sqlx::Error>(),
            Some(sqlx::Error::RowNotFound)
        ));
        assert!(is_not_found(&error));
        assert_eq!(map_repo_error(error), StatusCode::NOT_FOUND);
    }

    #[test]
    fn database_error_text_is_not_used_for_http_classification() {
        let source = std::io::Error::new(
            std::io::ErrorKind::ConnectionRefused,
            "database host not found: conflict or invalid input",
        );
        let error =
            anyhow::Error::new(sqlx::Error::Io(source)).context("load user: record not found");

        assert!(matches!(
            error.downcast_ref::<sqlx::Error>(),
            Some(sqlx::Error::Io(_))
        ));
        assert_eq!(
            error
                .root_cause()
                .downcast_ref::<std::io::Error>()
                .expect("I/O source is retained")
                .kind(),
            std::io::ErrorKind::ConnectionRefused
        );
        assert!(!is_not_found(&error));
        assert_eq!(map_repo_error(error), StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[tokio::test]
    async fn missing_updates_and_deletes_return_absence() {
        let service = UserService::new(Arc::new(InMemoryUserRepository::default()));
        let id = UserId(Uuid::now_v7());
        let user = User {
            id: id.clone(),
            email: Some("missing@example.com".into()),
            username: Some("missing".into()),
            hashed_password: None,
            is_active: Some(true),
            is_superuser: Some(false),
            created_at: Utc::now(),
            updated_at: None,
        };

        assert!(service.update(id.clone(), user).await.unwrap().is_none());
        assert!(!service.delete(id).await.unwrap());
    }
}
