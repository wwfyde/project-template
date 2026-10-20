use super::map_error;
use crate::entities::user::{ActiveModel, COLUMN, Column, Entity, Model};
use crate::models::user::{User, UserId, UserPage, UserQuery, UserRepository, UserSort};
use crate::repositories::{
    RepositoryError, user_query_offset, user_search_pattern, validate_user_ids,
};
use anyhow::Result;
use async_trait::async_trait;
use sea_orm::sea_query::{Expr, ExprTrait, Func, LikeExpr, OnConflict};
use sea_orm::{
    AccessMode, ActiveModelTrait, Condition, DatabaseConnection, DbBackend, EntityTrait,
    IsolationLevel, PaginatorTrait, QueryFilter, QueryOrder, QuerySelect, SelectExt, Set,
    TransactionTrait,
};
use std::sync::Arc;

impl From<Model> for User {
    fn from(model: Model) -> Self {
        Self {
            id: UserId(model.id),
            email: Some(model.email),
            username: model.username,
            hashed_password: model.hashed_password,
            is_active: model.is_active,
            is_superuser: model.is_superuser,
            created_at: model.created_at.into(),
            updated_at: model.updated_at.map(|datetime| datetime.into()),
        }
    }
}

pub struct SeaOrmUserRepository {
    db: Arc<DatabaseConnection>,
}

impl SeaOrmUserRepository {
    pub fn new(db: Arc<DatabaseConnection>) -> Self {
        Self { db }
    }
}

#[async_trait]
impl UserRepository for SeaOrmUserRepository {
    async fn find_all(&self) -> Result<Vec<User>> {
        Entity::find()
            .order_by_asc(COLUMN.id)
            .all(&*self.db)
            .await
            .map(|users| users.into_iter().map(User::from).collect())
            .map_err(map_error)
    }

    async fn insert(&self, user: &User) -> Result<User> {
        insert_model(user)?
            .insert(&*self.db)
            .await
            .map(User::from)
            .map_err(map_error)
    }

    async fn save(&self, user: &User) -> Result<User> {
        Entity::insert(insert_model(user)?)
            .on_conflict(
                OnConflict::column(Column::Id)
                    .update_columns([
                        Column::Email,
                        Column::Username,
                        Column::HashedPassword,
                        Column::IsActive,
                        Column::IsSuperuser,
                        Column::UpdatedAt,
                    ])
                    .to_owned(),
            )
            .exec_with_returning(&*self.db)
            .await
            .map(User::from)
            .map_err(map_error)
    }

    async fn find_many(&self, ids: &[UserId]) -> Result<Vec<User>> {
        validate_user_ids(ids)?;
        if ids.is_empty() {
            return Ok(Vec::new());
        }
        Entity::find()
            .filter(COLUMN.id.is_in(ids.iter().map(|id| id.0)))
            .order_by_asc(COLUMN.id)
            .all(&*self.db)
            .await
            .map(|users| users.into_iter().map(User::from).collect())
            .map_err(map_error)
    }

    async fn find_by_id(&self, id: UserId) -> Result<Option<User>> {
        Entity::find_by_id(id.0)
            .one(&*self.db)
            .await
            .map(|user| user.map(User::from))
            .map_err(map_error)
    }

    async fn exists_by_id(&self, id: UserId) -> Result<bool> {
        Entity::find_by_id(id.0)
            .exists(&*self.db)
            .await
            .map_err(map_error)
    }

    async fn find_by_email(&self, email: &str) -> Result<Option<User>> {
        Entity::find_by_email(email)
            .one(&*self.db)
            .await
            .map(|user| user.map(User::from))
            .map_err(map_error)
    }

    async fn search(&self, query: &UserQuery) -> Result<UserPage> {
        let offset = user_query_offset(query)?;
        let mut selection = Entity::find();
        if let Some(pattern) = user_search_pattern(query) {
            selection = selection.filter(
                Condition::any()
                    .add(
                        Func::lower(Expr::col((Entity, Column::Username)))
                            .like(LikeExpr::new(pattern.clone()).escape('!')),
                    )
                    .add(
                        Func::lower(Expr::col((Entity, Column::Email)))
                            .like(LikeExpr::new(pattern).escape('!')),
                    ),
            );
        }
        if let Some(is_active) = query.is_active {
            selection = selection.filter(COLUMN.is_active.eq(is_active));
        }
        if let Some(is_superuser) = query.is_superuser {
            selection = selection.filter(COLUMN.is_superuser.eq(is_superuser));
        }

        let transaction = if self.db.get_database_backend() == DbBackend::Postgres {
            self.db
                .begin_with_config(
                    Some(IsolationLevel::RepeatableRead),
                    Some(AccessMode::ReadOnly),
                )
                .await
        } else {
            self.db.begin().await
        }
        .map_err(map_error)?;

        let total = selection
            .clone()
            .count(&transaction)
            .await
            .map_err(map_error)?;
        selection = match query.sort {
            UserSort::IdAsc => selection.order_by_asc(COLUMN.id),
            UserSort::IdDesc => selection.order_by_desc(COLUMN.id),
            UserSort::CreatedAtAsc => selection
                .order_by_asc(COLUMN.created_at)
                .order_by_asc(COLUMN.id),
            UserSort::CreatedAtDesc => selection
                .order_by_desc(COLUMN.created_at)
                .order_by_desc(COLUMN.id),
        };
        let items = selection
            .limit(query.page_size)
            .offset(offset)
            .all(&transaction)
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
        let active_model = ActiveModel {
            id: Set(user.id.0),
            email: Set(email.to_owned()),
            username: Set(user.username.clone()),
            hashed_password: Set(user.hashed_password.clone()),
            is_active: Set(user.is_active),
            is_superuser: Set(user.is_superuser),
            updated_at: Set(user.updated_at.map(|datetime| datetime.into())),
            ..Default::default()
        };
        active_model
            .update(&*self.db)
            .await
            .map(User::from)
            .map_err(map_error)
    }

    async fn delete_by_id(&self, id: UserId) -> Result<()> {
        let result = Entity::delete_by_id(id.0)
            .exec(&*self.db)
            .await
            .map_err(map_error)?;
        if result.rows_affected == 0 {
            return Err(RepositoryError::NotFound.into());
        }
        Ok(())
    }
}

fn insert_model(user: &User) -> Result<ActiveModel> {
    let email = crate::repositories::required_email(user)?;
    Ok(ActiveModel {
        id: Set(user.id.0),
        email: Set(email.to_owned()),
        username: Set(user.username.clone()),
        hashed_password: Set(user.hashed_password.clone()),
        is_active: Set(user.is_active),
        is_superuser: Set(user.is_superuser),
        created_at: Set(user.created_at.into()),
        updated_at: Set(user.updated_at.map(|datetime| datetime.into())),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{FixedOffset, TimeZone};
    use uuid::Uuid;

    #[test]
    fn converts_user_model() {
        let created_at = FixedOffset::east_opt(0)
            .unwrap()
            .with_ymd_and_hms(2024, 1, 1, 0, 0, 0)
            .unwrap();
        let model = Model {
            id: Uuid::now_v7(),
            email: "user@example.com".into(),
            username: Some("tester".into()),
            hashed_password: Some("hashed".into()),
            is_active: Some(true),
            is_superuser: Some(false),
            created_at,
            updated_at: None,
        };

        let domain_user = User::from(model.clone());
        assert_eq!(domain_user.id, UserId(model.id));
        assert_eq!(domain_user.email, Some(model.email));
        assert_eq!(domain_user.username, model.username);
        assert_eq!(domain_user.hashed_password, model.hashed_password);
        assert_eq!(domain_user.is_active, model.is_active);
        assert_eq!(domain_user.is_superuser, model.is_superuser);
        assert_eq!(domain_user.created_at, model.created_at);
        assert_eq!(
            domain_user.updated_at,
            model.updated_at.map(|datetime| datetime.into())
        );
    }
}
