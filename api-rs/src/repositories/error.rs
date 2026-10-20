/// Internal classification for callers that need to distinguish expected failures.
/// Repository interfaces expose anyhow::Result and do not depend on this type.
#[derive(Debug, thiserror::Error)]
pub(crate) enum RepositoryError {
    #[error("record not found")]
    NotFound,
    #[error("record already exists")]
    Conflict,
    #[error("invalid repository input: {0}")]
    InvalidInput(&'static str),
}
