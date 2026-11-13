//! Shared ownership and invariant errors for the content domains.
//!
//! An account is an ownership boundary, not an authorization decision. Application
//! services must still authorize the caller before loading or changing aggregates.

use uuid::Uuid;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct AccountId(pub Uuid);

pub type DomainResult<T> = Result<T, DomainError>;

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum DomainError {
    #[error("invalid {field}: {reason}")]
    InvalidValue {
        field: &'static str,
        reason: &'static str,
    },
    #[error("related objects must belong to the same account")]
    AccountMismatch,
    #[error("the reference already exists")]
    DuplicateReference,
    #[error("the reference does not exist")]
    ReferenceNotFound,
    #[error("the operation is not valid in the current state")]
    InvalidTransition,
    #[error("the revision or indexing attempt is no longer current")]
    RevisionMismatch,
}

pub(crate) fn require_non_blank(field: &'static str, value: &str) -> DomainResult<()> {
    if value.trim().is_empty() {
        return Err(DomainError::InvalidValue {
            field,
            reason: "must not be blank",
        });
    }
    Ok(())
}

pub(crate) fn ensure_same_account(expected: AccountId, actual: AccountId) -> DomainResult<()> {
    if expected != actual {
        return Err(DomainError::AccountMismatch);
    }
    Ok(())
}
