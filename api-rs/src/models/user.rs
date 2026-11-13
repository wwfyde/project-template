use crate::models::Locale;
use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct UserId(pub Uuid);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
#[schema(minimum = 1, maximum = 9223372036854775807_u64)]
pub struct Uid(pub u64);

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[error("UID must be a positive PostgreSQL BIGINT")]
pub struct InvalidUid;

impl TryFrom<i64> for Uid {
    type Error = InvalidUid;

    fn try_from(value: i64) -> std::result::Result<Self, Self::Error> {
        if value <= 0 {
            return Err(InvalidUid);
        }
        Ok(Self(u64::try_from(value).map_err(|_| InvalidUid)?))
    }
}

/// A persisted user, including the numeric identity assigned by its repository.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct User {
    /// User ID
    pub id: UserId,
    pub uid: Uid,
    pub email: Option<String>,
    pub nickname: Option<String>,
    pub username: Option<String>,
    pub hashed_password: Option<String>,
    pub is_active: Option<bool>,
    #[serde(default)]
    pub locale: Locale,
    pub is_superuser: Option<bool>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

/// Writable user data. UUID identifies the record; the repository assigns a UID
/// on insert and preserves it on update or an existing-record upsert.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UserWrite {
    pub id: UserId,
    pub email: Option<String>,
    pub nickname: Option<String>,
    pub username: Option<String>,
    pub hashed_password: Option<String>,
    pub is_active: Option<bool>,
    pub locale: Locale,
    pub is_superuser: Option<bool>,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

impl From<&User> for UserWrite {
    fn from(user: &User) -> Self {
        Self {
            id: user.id.clone(),
            email: user.email.clone(),
            nickname: user.nickname.clone(),
            username: user.username.clone(),
            hashed_password: user.hashed_password.clone(),
            is_active: user.is_active,
            locale: user.locale,
            is_superuser: user.is_superuser,
            created_at: user.created_at,
            updated_at: user.updated_at,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum UserSort {
    #[default]
    IdAsc,
    IdDesc,
    CreatedAtAsc,
    CreatedAtDesc,
}

/// A bounded user search, independent of SQLx and SeaORM query builders.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UserQuery {
    /// Literal substring in username or email; blank input disables this filter.
    pub keyword: Option<String>,
    pub is_active: Option<bool>,
    pub is_superuser: Option<bool>,
    /// One-based page number.
    pub page: u64,
    /// Between 1 and 100, inclusive.
    pub page_size: u64,
    pub sort: UserSort,
}

impl Default for UserQuery {
    fn default() -> Self {
        Self {
            keyword: None,
            is_active: None,
            is_superuser: None,
            page: 1,
            page_size: 20,
            sort: UserSort::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UserPage {
    pub items: Vec<User>,
    /// Number of matching users before pagination, from the same snapshot as items.
    pub total: u64,
    pub page: u64,
    pub page_size: u64,
}

#[async_trait::async_trait]
pub trait UserRepository: Send + Sync {
    //  Sea-ORM data视角, 实体查找 对象保存
    // 数据持久化风格: 一个需要被查找、插入、保存的对象或记录, 数据存储
    async fn find_all(&self) -> Result<Vec<User>>;
    async fn insert(&self, user: &UserWrite) -> Result<User>;
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>>;
    /// Batch lookup, at most 1000 IDs; missing IDs are omitted and results are unique, ID ascending.
    async fn find_many(&self, ids: &[UserId]) -> Result<Vec<User>>;
    async fn find_by_email(&self, email: &str) -> Result<Option<User>>;
    async fn update(&self, user: &UserWrite) -> Result<User>;
    /// Atomic upsert by UUID. Existing UID and creation time are preserved.
    async fn save(&self, user: &UserWrite) -> Result<User>;
    async fn search(&self, query: &UserQuery) -> Result<UserPage>;
    async fn delete_by_id(&self, id: UserId) -> Result<()>;
    async fn exists_by_id(&self, id: UserId) -> Result<bool> {
        Ok(self.find_by_id(id).await?.is_some())
    }

    // 资源操作风格: 一个可以被创建、获取、修改的资源
    // create：创建资源。
    // get: 获取
    // list: 获取全部
    // insert：插入记录。
    // update: 修改
    // upsert：明确表达存在则更新、不存在则插入。
    // delete：删除目标资源或记录。
    // exists: 是否存在
    // count: 计数

    //集合 / 仓储(collection)
    // add find save remove, contains,  counts
    // replace
}
