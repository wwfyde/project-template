mod error;
pub mod in_memory;
pub mod orm;
pub mod sqlx;

pub use crate::models::student::{NewStudent, Student, StudentRepository};
pub use crate::models::todo::{Todo, TodoRepository};
pub use crate::models::user::{User, UserId, UserPage, UserQuery, UserRepository, UserSort};
pub(crate) use error::RepositoryError;

fn required_email(user: &User) -> anyhow::Result<&str> {
    user.email
        .as_deref()
        .ok_or_else(|| anyhow::Error::new(RepositoryError::InvalidInput("user email is required")))
}

fn validate_user_ids(ids: &[UserId]) -> anyhow::Result<()> {
    if ids.len() > 1000 {
        return Err(
            RepositoryError::InvalidInput("find_many accepts at most 1000 user IDs").into(),
        );
    }
    Ok(())
}

fn user_query_offset(query: &UserQuery) -> anyhow::Result<u64> {
    if !(1..=100).contains(&query.page_size) {
        return Err(RepositoryError::InvalidInput("page_size must be between 1 and 100").into());
    }
    query
        .page
        .checked_sub(1)
        .and_then(|page| page.checked_mul(query.page_size))
        .filter(|offset| *offset <= i64::MAX as u64)
        .ok_or_else(|| {
            RepositoryError::InvalidInput("page must be positive and its offset must fit in i64")
                .into()
        })
}

fn normalized_user_keyword(query: &UserQuery) -> Option<String> {
    query
        .keyword
        .as_deref()
        .map(str::trim)
        .filter(|keyword| !keyword.is_empty())
        .map(str::to_lowercase)
}

fn user_search_pattern(query: &UserQuery) -> Option<String> {
    normalized_user_keyword(query).map(|keyword| {
        let mut pattern = String::from("%");
        for character in keyword.chars() {
            if matches!(character, '!' | '%' | '_') {
                pattern.push('!');
            }
            pattern.push(character);
        }
        pattern.push('%');
        pattern
    })
}

#[cfg(test)]
mod tests;
