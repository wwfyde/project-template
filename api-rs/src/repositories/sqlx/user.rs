use super::map_error;
use crate::models::user::{User, UserId, UserPage, UserQuery, UserRepository, UserSort};
use crate::repositories::{
    RepositoryError, user_query_offset, user_search_pattern, validate_user_ids,
};
use ::sqlx::{FromRow, PgPool, Postgres, QueryBuilder};
use anyhow::Result;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use uuid::Uuid;

#[derive(FromRow)]
struct UserRow {
    id: Uuid,
    email: String,
    username: Option<String>,
    hashed_password: Option<String>,
    is_active: Option<bool>,
    is_superuser: Option<bool>,
    created_at: DateTime<Utc>,
    updated_at: Option<DateTime<Utc>>,
}

impl From<UserRow> for User {
    fn from(row: UserRow) -> Self {
        Self {
            id: UserId(row.id),
            email: Some(row.email),
            username: row.username,
            hashed_password: row.hashed_password,
            is_active: row.is_active,
            is_superuser: row.is_superuser,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }
}

pub struct SqlxUserRepository {
    pool: PgPool,
}

impl SqlxUserRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl UserRepository for SqlxUserRepository {
    async fn find_all(&self) -> Result<Vec<User>> {
        ::sqlx::query_as::<_, UserRow>(
            r#"SELECT id, email, username, hashed_password, is_active, is_superuser,
                      created_at, updated_at
               FROM public."user"
               ORDER BY id ASC"#,
        )
        .fetch_all(&self.pool)
        .await
        .map(|users| users.into_iter().map(User::from).collect())
        .map_err(map_error)
    }

    async fn find_many(&self, ids: &[UserId]) -> Result<Vec<User>> {
        validate_user_ids(ids)?;
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        let ids: Vec<Uuid> = ids.iter().map(|id| id.0).collect();
        ::sqlx::query_as::<_, UserRow>(
            r#"SELECT id, email, username, hashed_password, is_active, is_superuser,
                      created_at, updated_at
               FROM public."user"
               WHERE id = ANY($1)
               ORDER BY id ASC"#,
        )
        .bind(ids)
        .fetch_all(&self.pool)
        .await
        .map(|users| users.into_iter().map(User::from).collect())
        .map_err(map_error)
    }

    async fn insert(&self, user: &User) -> Result<User> {
        let email = crate::repositories::required_email(user)?;
        ::sqlx::query_as::<_, UserRow>(
            r#"INSERT INTO public."user"
                   (id, email, username, hashed_password, is_active, is_superuser,
                    created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING id, email, username, hashed_password, is_active, is_superuser,
                         created_at, updated_at"#,
        )
        .bind(user.id.0)
        .bind(email)
        .bind(user.username.as_deref())
        .bind(user.hashed_password.as_deref())
        .bind(user.is_active)
        .bind(user.is_superuser)
        .bind(user.created_at)
        .bind(user.updated_at)
        .fetch_one(&self.pool)
        .await
        .map(User::from)
        .map_err(map_error)
    }

    async fn save(&self, user: &User) -> Result<User> {
        let email = crate::repositories::required_email(user)?;
        ::sqlx::query_as::<_, UserRow>(
            r#"INSERT INTO public."user"
                   (id, email, username, hashed_password, is_active, is_superuser,
                    created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (id) DO UPDATE
               SET email = EXCLUDED.email,
                   username = EXCLUDED.username,
                   hashed_password = EXCLUDED.hashed_password,
                   is_active = EXCLUDED.is_active,
                   is_superuser = EXCLUDED.is_superuser,
                   updated_at = EXCLUDED.updated_at
               RETURNING id, email, username, hashed_password, is_active, is_superuser,
                         created_at, updated_at"#,
        )
        .bind(user.id.0)
        .bind(email)
        .bind(user.username.as_deref())
        .bind(user.hashed_password.as_deref())
        .bind(user.is_active)
        .bind(user.is_superuser)
        .bind(user.created_at)
        .bind(user.updated_at)
        .fetch_one(&self.pool)
        .await
        .map(User::from)
        .map_err(map_error)
    }

    async fn find_by_id(&self, id: UserId) -> Result<Option<User>> {
        ::sqlx::query_as::<_, UserRow>(
            r#"SELECT id, email, username, hashed_password, is_active, is_superuser,
                      created_at, updated_at
               FROM public."user"
               WHERE id = $1"#,
        )
        .bind(id.0)
        .fetch_optional(&self.pool)
        .await
        .map(|user| user.map(User::from))
        .map_err(map_error)
    }

    async fn find_by_email(&self, email: &str) -> Result<Option<User>> {
        ::sqlx::query_as::<_, UserRow>(
            r#"SELECT id, email, username, hashed_password, is_active, is_superuser,
                      created_at, updated_at
               FROM public."user"
               WHERE email = $1"#,
        )
        .bind(email)
        .fetch_optional(&self.pool)
        .await
        .map(|user| user.map(User::from))
        .map_err(map_error)
    }

    async fn search(&self, query: &UserQuery) -> Result<UserPage> {
        let offset = i64::try_from(user_query_offset(query)?)?;
        let page_size = i64::try_from(query.page_size)?;
        let pattern = user_search_pattern(query);
        let mut transaction = self
            .pool
            .begin_with("BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            .await
            .map_err(map_error)?;

        let mut count =
            QueryBuilder::<Postgres>::new(r#"SELECT COUNT(*) FROM public."user" WHERE TRUE"#);
        push_search_filters(&mut count, query, pattern.as_deref());
        let total = count
            .build_query_scalar::<i64>()
            .fetch_one(&mut *transaction)
            .await
            .map_err(map_error)?;
        let total = u64::try_from(total)?;

        let mut page = QueryBuilder::<Postgres>::new(
            r#"SELECT id, email, username, hashed_password, is_active, is_superuser,
                      created_at, updated_at
               FROM public."user" WHERE TRUE"#,
        );
        push_search_filters(&mut page, query, pattern.as_deref());
        page.push(match query.sort {
            UserSort::IdAsc => " ORDER BY id ASC",
            UserSort::IdDesc => " ORDER BY id DESC",
            UserSort::CreatedAtAsc => " ORDER BY created_at ASC, id ASC",
            UserSort::CreatedAtDesc => " ORDER BY created_at DESC, id DESC",
        });
        page.push(" LIMIT ")
            .push_bind(page_size)
            .push(" OFFSET ")
            .push_bind(offset);
        let items = page
            .build_query_as::<UserRow>()
            .fetch_all(&mut *transaction)
            .await
            .map_err(map_error)?
            .into_iter()
            .map(User::from)
            .collect();
        transaction.commit().await.map_err(map_error)?;

        Ok(UserPage {
            items,
            total,
            page: query.page,
            page_size: query.page_size,
        })
    }

    async fn update(&self, user: &User) -> Result<User> {
        let email = crate::repositories::required_email(user)?;
        ::sqlx::query_as::<_, UserRow>(
            r#"UPDATE public."user"
               SET email = $2, username = $3, hashed_password = $4,
                   is_active = $5, is_superuser = $6, updated_at = $7
               WHERE id = $1
               RETURNING id, email, username, hashed_password, is_active, is_superuser,
                         created_at, updated_at"#,
        )
        .bind(user.id.0)
        .bind(email)
        .bind(user.username.as_deref())
        .bind(user.hashed_password.as_deref())
        .bind(user.is_active)
        .bind(user.is_superuser)
        .bind(user.updated_at)
        .fetch_optional(&self.pool)
        .await
        .map_err(map_error)?
        .map(User::from)
        .ok_or_else(|| anyhow::Error::new(RepositoryError::NotFound))
    }

    async fn delete_by_id(&self, id: UserId) -> Result<()> {
        let result = ::sqlx::query(r#"DELETE FROM public."user" WHERE id = $1"#)
            .bind(id.0)
            .execute(&self.pool)
            .await
            .map_err(map_error)?;
        if result.rows_affected() == 0 {
            return Err(RepositoryError::NotFound.into());
        }
        Ok(())
    }

    async fn exists_by_id(&self, id: UserId) -> Result<bool> {
        ::sqlx::query_scalar::<_, bool>(
            r#"SELECT EXISTS(SELECT 1 FROM public."user" WHERE id = $1)"#,
        )
        .bind(id.0)
        .fetch_one(&self.pool)
        .await
        .map_err(map_error)
    }
}

fn push_search_filters(
    builder: &mut QueryBuilder<Postgres>,
    query: &UserQuery,
    pattern: Option<&str>,
) {
    if let Some(pattern) = pattern {
        builder
            .push(" AND (LOWER(username) LIKE ")
            .push_bind(pattern)
            .push(" ESCAPE '!' OR LOWER(email) LIKE ")
            .push_bind(pattern)
            .push(" ESCAPE '!')");
    }
    if let Some(is_active) = query.is_active {
        builder.push(" AND is_active = ").push_bind(is_active);
    }
    if let Some(is_superuser) = query.is_superuser {
        builder.push(" AND is_superuser = ").push_bind(is_superuser);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn converts_user_row() {
        let id = Uuid::now_v7();
        let created_at = Utc.with_ymd_and_hms(2024, 1, 1, 0, 0, 0).unwrap();
        let updated_at = Utc.with_ymd_and_hms(2024, 1, 2, 0, 0, 0).unwrap();
        let user = User::from(UserRow {
            id,
            email: "user@example.com".into(),
            username: Some("tester".into()),
            hashed_password: Some("hashed".into()),
            is_active: Some(true),
            is_superuser: None,
            created_at,
            updated_at: Some(updated_at),
        });

        assert_eq!(user.id, UserId(id));
        assert_eq!(user.email.as_deref(), Some("user@example.com"));
        assert_eq!(user.username.as_deref(), Some("tester"));
        assert_eq!(user.hashed_password.as_deref(), Some("hashed"));
        assert_eq!(user.is_active, Some(true));
        assert_eq!(user.is_superuser, None);
        assert_eq!(user.created_at, created_at);
        assert_eq!(user.updated_at, Some(updated_at));
    }
}
