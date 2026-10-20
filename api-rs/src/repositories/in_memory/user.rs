use crate::models::user::{User, UserId, UserPage, UserQuery, UserRepository, UserSort};
use crate::repositories::{
    RepositoryError, normalized_user_keyword, required_email, user_query_offset, validate_user_ids,
};
use anyhow::Result;
use async_trait::async_trait;
use std::cmp::Reverse;
use std::collections::BTreeSet;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone, Default)]
pub struct InMemoryUserRepository {
    data: Arc<RwLock<Vec<User>>>,
}

#[async_trait]
impl UserRepository for InMemoryUserRepository {
    async fn find_all(&self) -> Result<Vec<User>> {
        let mut users = self.data.read().await.clone();
        users.sort_by_key(|user| user.id.0);
        Ok(users)
    }

    async fn insert(&self, user: &User) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        if data
            .iter()
            .any(|existing| existing.id == user.id || existing.email.as_deref() == Some(email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        data.push(user.clone());
        Ok(user.clone())
    }

    async fn find_many(&self, ids: &[UserId]) -> Result<Vec<User>> {
        validate_user_ids(ids)?;
        let ids: BTreeSet<_> = ids.iter().map(|id| id.0).collect();
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        let mut users: Vec<_> = self
            .data
            .read()
            .await
            .iter()
            .filter(|user| ids.contains(&user.id.0))
            .cloned()
            .collect();
        users.sort_by_key(|user| user.id.0);
        Ok(users)
    }

    async fn find_by_id(&self, id: UserId) -> Result<Option<User>> {
        Ok(self
            .data
            .read()
            .await
            .iter()
            .find(|user| user.id == id)
            .cloned())
    }

    async fn find_by_email(&self, email: &str) -> Result<Option<User>> {
        Ok(self
            .data
            .read()
            .await
            .iter()
            .find(|user| user.email.as_deref() == Some(email))
            .cloned())
    }

    async fn update(&self, user: &User) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        let index = data
            .iter()
            .position(|existing| existing.id == user.id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        if data
            .iter()
            .any(|existing| existing.id != user.id && existing.email.as_deref() == Some(email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        let mut updated = user.clone();
        updated.created_at = data[index].created_at;
        data[index] = updated.clone();
        Ok(updated)
    }

    async fn save(&self, user: &User) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        let index = data.iter().position(|existing| existing.id == user.id);
        if data
            .iter()
            .any(|existing| existing.id != user.id && existing.email.as_deref() == Some(email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        let mut saved = user.clone();
        if let Some(index) = index {
            saved.created_at = data[index].created_at;
            data[index] = saved.clone();
        } else {
            data.push(saved.clone());
        }
        Ok(saved)
    }

    async fn search(&self, query: &UserQuery) -> Result<UserPage> {
        let offset = user_query_offset(query)?;
        let limit = usize::try_from(query.page_size)?;
        let keyword = normalized_user_keyword(query);
        let mut users: Vec<_> = self
            .data
            .read()
            .await
            .iter()
            .filter(|user| {
                query
                    .is_active
                    .is_none_or(|active| user.is_active == Some(active))
                    && query
                        .is_superuser
                        .is_none_or(|superuser| user.is_superuser == Some(superuser))
                    && keyword.as_deref().is_none_or(|keyword| {
                        [user.username.as_deref(), user.email.as_deref()]
                            .into_iter()
                            .flatten()
                            .any(|value| value.to_lowercase().contains(keyword))
                    })
            })
            .cloned()
            .collect();
        let total = users.len() as u64;
        match query.sort {
            UserSort::IdAsc => users.sort_by_key(|user| user.id.0),
            UserSort::IdDesc => users.sort_by_key(|user| Reverse(user.id.0)),
            UserSort::CreatedAtAsc => users.sort_by_key(|user| (user.created_at, user.id.0)),
            UserSort::CreatedAtDesc => {
                users.sort_by_key(|user| Reverse((user.created_at, user.id.0)));
            }
        }
        let items = match usize::try_from(offset) {
            Ok(offset) => users.into_iter().skip(offset).take(limit).collect(),
            Err(_) => Vec::new(),
        };
        Ok(UserPage {
            items,
            total,
            page: query.page,
            page_size: query.page_size,
        })
    }

    async fn delete_by_id(&self, id: UserId) -> Result<()> {
        let mut data = self.data.write().await;
        let index = data
            .iter()
            .position(|user| user.id == id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        data.remove(index);
        Ok(())
    }

    async fn exists_by_id(&self, id: UserId) -> Result<bool> {
        Ok(self.data.read().await.iter().any(|user| user.id == id))
    }
}
