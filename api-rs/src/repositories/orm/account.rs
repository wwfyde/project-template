//! Transactional registration, billing-container membership, and resource access.

mod helpers;
mod members;
#[cfg(test)]
mod tests;

use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use chrono::Utc;
use sea_orm::{
    ActiveModelTrait, ColumnTrait, DatabaseConnection, DatabaseTransaction, EntityTrait,
    QueryFilter, QueryOrder, Set, TransactionTrait,
};
use uuid::Uuid;

use crate::entities::{account, account_member, tenant, tenant_member};
use crate::models::account::{Account, AccountAccess, AccountKind, AccountMember, MemberRole};
use crate::models::account_repository::AccountRepository;
use crate::models::shared::AccountId;
use crate::models::tenant::{Tenant, TenantId, TenantKind, TenantMember};
use crate::models::user::{User, UserId, UserWrite};
use crate::repositories::RepositoryError;

use super::map_error;
use helpers::*;

pub struct SeaOrmAccountRepository {
    db: Arc<DatabaseConnection>,
}

impl SeaOrmAccountRepository {
    pub fn new(db: Arc<DatabaseConnection>) -> Self {
        Self { db }
    }
}

#[async_trait]
impl AccountRepository for SeaOrmAccountRepository {
    async fn register_user(&self, input: &UserWrite) -> Result<User> {
        let tx = self.db.begin().await.map_err(map_error)?;
        let user = super::user::insert_model(input)?
            .insert(&tx)
            .await
            .map_err(map_error)?;
        let user = User::try_from(user)?;
        let tenant = Tenant::personal(
            TenantId(Uuid::now_v7()),
            user.id.clone(),
            "Personal",
            input.created_at,
        )?;
        let account = Account::personal(
            AccountId(Uuid::now_v7()),
            &tenant,
            user.id.clone(),
            "Personal",
            input.created_at,
        )?;
        insert_tenant(&tx, &tenant).await?;
        insert_tenant_owner(&tx, tenant.id, &user.id, input.created_at).await?;
        insert_account(&tx, &account).await?;
        insert_account_owner(&tx, account.id, &user.id, input.created_at).await?;
        tx.commit().await.map_err(map_error)?;
        Ok(user)
    }

    async fn list_tenants(&self, actor: UserId) -> Result<Vec<Tenant>> {
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let memberships = tenant_member::Entity::find()
            .filter(tenant_member::Column::UserId.eq(actor.0))
            .all(&tx)
            .await
            .map_err(map_error)?;
        let ids = memberships
            .into_iter()
            .map(|member| member.tenant_id)
            .collect::<Vec<_>>();
        let rows = tenant::Entity::find()
            .filter(tenant::Column::Id.is_in(ids))
            .filter(tenant::Column::IsActive.eq(true))
            .order_by_asc(tenant::Column::CreatedAt)
            .order_by_asc(tenant::Column::Id)
            .all(&tx)
            .await
            .map_err(map_error)?;
        let mut tenants = Vec::new();
        for row in rows {
            let tenant = tenant_from_model(row)?;
            if tenant.kind != TenantKind::Personal
                || tenant.personal_user_id.as_ref() == Some(&actor)
            {
                tenant_role(&tx, &tenant, &actor).await?;
                tenants.push(tenant);
            }
        }
        tx.commit().await.map_err(map_error)?;
        Ok(tenants)
    }

    async fn create_tenant(&self, actor: UserId, name: &str) -> Result<Tenant> {
        ensure_name(name)?;
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let tenant = Tenant::organization(TenantId(Uuid::now_v7()), name, Utc::now())?;
        insert_tenant(&tx, &tenant).await?;
        insert_tenant_owner(&tx, tenant.id, &actor, tenant.created_at).await?;
        tx.commit().await.map_err(map_error)?;
        Ok(tenant)
    }

    async fn list_accounts(&self, actor: UserId) -> Result<Vec<Account>> {
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let memberships = account_member::Entity::find()
            .filter(account_member::Column::UserId.eq(actor.0))
            .order_by_asc(account_member::Column::CreatedAt)
            .order_by_asc(account_member::Column::AccountId)
            .all(&tx)
            .await
            .map_err(map_error)?;
        let mut accounts = Vec::new();
        for member in memberships {
            match authorize_account(&tx, &actor, AccountId(member.account_id), false).await {
                Ok((_, account, _)) => accounts.push(account),
                Err(error)
                    if matches!(
                        error.downcast_ref::<RepositoryError>(),
                        Some(RepositoryError::NotFound | RepositoryError::Forbidden)
                    ) => {}
                Err(error) => return Err(error),
            }
        }
        tx.commit().await.map_err(map_error)?;
        Ok(accounts)
    }

    async fn get_account(&self, actor: UserId, id: AccountId) -> Result<Account> {
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let (_, account, _) = authorize_account(&tx, &actor, id, false).await?;
        tx.commit().await.map_err(map_error)?;
        Ok(account)
    }

    async fn resolve_account(
        &self,
        actor: UserId,
        selected: Option<AccountId>,
    ) -> Result<AccountAccess> {
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let id = match selected {
            Some(id) => id,
            None => {
                let personal = account::Entity::find()
                    .filter(account::Column::PersonalUserId.eq(actor.0))
                    .filter(account::Column::Kind.eq(AccountKind::Personal.as_str()))
                    .one(&tx)
                    .await
                    .map_err(map_error)?
                    .ok_or(RepositoryError::NotFound)?;
                AccountId(personal.id)
            }
        };
        let (tenant, account, role) = authorize_account(&tx, &actor, id, false).await?;
        tx.commit().await.map_err(map_error)?;
        Ok(AccountAccess {
            user_id: actor,
            account_id: account.id,
            tenant_id: tenant.id,
            role,
        })
    }

    async fn create_workspace(
        &self,
        actor: UserId,
        tenant_id: TenantId,
        name: &str,
    ) -> Result<Account> {
        ensure_name(name)?;
        let tx = self.db.begin().await.map_err(map_error)?;
        ensure_active_user(&tx, &actor).await?;
        let tenant = load_tenant(&tx, tenant_id, true).await?;
        let role = tenant_role(&tx, &tenant, &actor).await?;
        if tenant.kind != TenantKind::Organization || !role.can_manage() {
            return Err(RepositoryError::Forbidden.into());
        }
        let account = Account::workspace(AccountId(Uuid::now_v7()), &tenant, name, Utc::now())?;
        insert_account(&tx, &account).await?;
        insert_account_owner(&tx, account.id, &actor, account.created_at).await?;
        tx.commit().await.map_err(map_error)?;
        Ok(account)
    }

    async fn tenant_members(&self, actor: UserId, tenant: TenantId) -> Result<Vec<TenantMember>> {
        members::tenant_members(&self.db, actor, tenant).await
    }
    async fn put_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
        role: MemberRole,
    ) -> Result<TenantMember> {
        members::put_tenant_member(&self.db, actor, tenant, target, role).await
    }
    async fn remove_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
    ) -> Result<()> {
        members::remove_tenant_member(&self.db, actor, tenant, target).await
    }
    async fn account_members(
        &self,
        actor: UserId,
        account: AccountId,
    ) -> Result<Vec<AccountMember>> {
        members::account_members(&self.db, actor, account).await
    }
    async fn put_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
        role: MemberRole,
    ) -> Result<AccountMember> {
        members::put_account_member(&self.db, actor, account, target, role).await
    }
    async fn remove_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
    ) -> Result<()> {
        members::remove_account_member(&self.db, actor, account, target).await
    }
}

async fn insert_tenant(tx: &DatabaseTransaction, value: &Tenant) -> Result<()> {
    tenant::ActiveModel {
        id: Set(value.id.0),
        name: Set(value.name.clone()),
        kind: Set(value.kind.as_str().to_owned()),
        personal_user_id: Set(value.personal_user_id.as_ref().map(|id| id.0)),
        is_active: Set(value.is_active),
        created_at: Set(value.created_at.into()),
    }
    .insert(tx)
    .await
    .map_err(map_error)?;
    Ok(())
}

async fn insert_account(tx: &DatabaseTransaction, value: &Account) -> Result<()> {
    account::ActiveModel {
        id: Set(value.id.0),
        tenant_id: Set(value.tenant_id.0),
        name: Set(value.name.clone()),
        kind: Set(value.kind.as_str().to_owned()),
        personal_user_id: Set(value.personal_user_id.as_ref().map(|id| id.0)),
        is_active: Set(value.is_active),
        created_at: Set(value.created_at.into()),
    }
    .insert(tx)
    .await
    .map_err(map_error)?;
    Ok(())
}

async fn insert_tenant_owner(
    tx: &DatabaseTransaction,
    tenant: TenantId,
    actor: &UserId,
    at: chrono::DateTime<Utc>,
) -> Result<()> {
    tenant_member::ActiveModel {
        tenant_id: Set(tenant.0),
        user_id: Set(actor.0),
        role: Set(MemberRole::Owner.as_str().to_owned()),
        created_at: Set(at.into()),
    }
    .insert(tx)
    .await
    .map_err(map_error)?;
    Ok(())
}

async fn insert_account_owner(
    tx: &DatabaseTransaction,
    account: AccountId,
    actor: &UserId,
    at: chrono::DateTime<Utc>,
) -> Result<()> {
    account_member::ActiveModel {
        account_id: Set(account.0),
        user_id: Set(actor.0),
        role: Set(MemberRole::Owner.as_str().to_owned()),
        created_at: Set(at.into()),
    }
    .insert(tx)
    .await
    .map_err(map_error)?;
    Ok(())
}
