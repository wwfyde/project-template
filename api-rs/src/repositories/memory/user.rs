use crate::models::user::{
    Uid, User, UserId, UserPage, UserQuery, UserRepository, UserSort, UserWrite,
};
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
    data: Arc<RwLock<UserState>>,
}

struct UserState {
    users: Vec<User>,
    next_uid: Option<i64>,
}

impl Default for UserState {
    fn default() -> Self {
        Self {
            users: Vec::new(),
            next_uid: Some(1),
        }
    }
}

impl UserState {
    fn allocate_uid(&mut self) -> Result<Uid> {
        let value = self
            .next_uid
            .ok_or_else(|| anyhow::anyhow!("user UID sequence exhausted"))?;
        let uid = Uid::try_from(value)?;
        self.next_uid = value.checked_add(1);
        Ok(uid)
    }
}

fn conflicts(existing: &User, input: &UserWrite, email: &str) -> bool {
    existing.email.as_deref() == Some(email)
        || input
            .username
            .as_deref()
            .is_some_and(|username| existing.username.as_deref() == Some(username))
}

fn persisted_user(input: &UserWrite, uid: Uid, created_at: chrono::DateTime<chrono::Utc>) -> User {
    User {
        id: input.id.clone(),
        uid,
        email: input.email.clone(),
        nickname: input.nickname.clone(),
        username: input.username.clone(),
        hashed_password: input.hashed_password.clone(),
        is_active: input.is_active,
        locale: input.locale,
        is_superuser: input.is_superuser,
        created_at,
        updated_at: input.updated_at,
    }
}

#[async_trait]
impl UserRepository for InMemoryUserRepository {
    async fn find_all(&self) -> Result<Vec<User>> {
        let mut users = self.data.read().await.users.clone();
        users.sort_by_key(|user| user.id.0);
        Ok(users)
    }

    async fn insert(&self, user: &UserWrite) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        if data
            .users
            .iter()
            .any(|existing| existing.id == user.id || conflicts(existing, user, email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        let uid = data.allocate_uid()?;
        let inserted = persisted_user(user, uid, user.created_at);
        data.users.push(inserted.clone());
        Ok(inserted)
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
            .users
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
            .users
            .iter()
            .find(|user| user.id == id)
            .cloned())
    }

    async fn find_by_email(&self, email: &str) -> Result<Option<User>> {
        Ok(self
            .data
            .read()
            .await
            .users
            .iter()
            .find(|user| user.email.as_deref() == Some(email))
            .cloned())
    }

    async fn update(&self, user: &UserWrite) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        let index = data
            .users
            .iter()
            .position(|existing| existing.id == user.id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        if data
            .users
            .iter()
            .any(|existing| existing.id != user.id && conflicts(existing, user, email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        let original = &data.users[index];
        let updated = persisted_user(user, original.uid.clone(), original.created_at);
        data.users[index] = updated.clone();
        Ok(updated)
    }

    async fn save(&self, user: &UserWrite) -> Result<User> {
        let email = required_email(user)?;
        let mut data = self.data.write().await;
        let index = data
            .users
            .iter()
            .position(|existing| existing.id == user.id);
        if data
            .users
            .iter()
            .any(|existing| existing.id != user.id && conflicts(existing, user, email))
        {
            return Err(RepositoryError::Conflict.into());
        }
        let saved = if let Some(index) = index {
            let original = &data.users[index];
            let saved = persisted_user(user, original.uid.clone(), original.created_at);
            data.users[index] = saved.clone();
            saved
        } else {
            let uid = data.allocate_uid()?;
            let saved = persisted_user(user, uid, user.created_at);
            data.users.push(saved.clone());
            saved
        };
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
            .users
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
            .users
            .iter()
            .position(|user| user.id == id)
            .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))?;
        data.users.remove(index);
        Ok(())
    }

    async fn exists_by_id(&self, id: UserId) -> Result<bool> {
        Ok(self
            .data
            .read()
            .await
            .users
            .iter()
            .any(|user| user.id == id))
    }
}
