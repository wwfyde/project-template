use anyhow::Result;
use sea_orm::{
    ColumnTrait, ConnectionTrait, DatabaseTransaction, DbBackend, EntityTrait, QueryFilter,
    QuerySelect,
};

use crate::entities::{account, account_member, tenant, tenant_member, user};
use crate::models::account::{Account, AccountKind, AccountMember, MemberRole};
use crate::models::shared::AccountId;
use crate::models::tenant::{Tenant, TenantId, TenantKind, TenantMember};
use crate::models::user::UserId;
use crate::repositories::RepositoryError;

use super::super::map_error;

pub(super) fn tenant_from_model(model: tenant::Model) -> Result<Tenant> {
    Ok(Tenant {
        id: TenantId(model.id),
        name: model.name,
        kind: model.kind.parse()?,
        personal_user_id: model.personal_user_id.map(UserId),
        is_active: model.is_active,
        created_at: model.created_at.into(),
    })
}

pub(super) fn account_from_model(model: account::Model) -> Result<Account> {
    Ok(Account {
        id: AccountId(model.id),
        tenant_id: TenantId(model.tenant_id),
        name: model.name,
        kind: model.kind.parse()?,
        personal_user_id: model.personal_user_id.map(UserId),
        is_active: model.is_active,
        created_at: model.created_at.into(),
    })
}

pub(super) fn tenant_member_from_model(model: tenant_member::Model) -> Result<TenantMember> {
    Ok(TenantMember {
        tenant_id: TenantId(model.tenant_id),
        user_id: UserId(model.user_id),
        role: model.role.parse()?,
        created_at: model.created_at.into(),
    })
}

pub(super) fn account_member_from_model(model: account_member::Model) -> Result<AccountMember> {
    Ok(AccountMember {
        account_id: AccountId(model.account_id),
        user_id: UserId(model.user_id),
        role: model.role.parse()?,
        created_at: model.created_at.into(),
    })
}

pub(super) async fn ensure_active_user(tx: &DatabaseTransaction, id: &UserId) -> Result<()> {
    let user = user::Entity::find_by_id(id.0)
        .one(tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::NotFound)?;
    if user.is_active != Some(true) {
        return Err(RepositoryError::Forbidden.into());
    }
    Ok(())
}

pub(super) async fn load_tenant(
    tx: &DatabaseTransaction,
    id: TenantId,
    lock: bool,
) -> Result<Tenant> {
    let mut query = tenant::Entity::find_by_id(id.0);
    if lock && tx.get_database_backend() == DbBackend::Postgres {
        query = query.lock_exclusive();
    }
    let tenant = tenant_from_model(
        query
            .one(tx)
            .await
            .map_err(map_error)?
            .ok_or(RepositoryError::NotFound)?,
    )?;
    if !tenant.is_active {
        return Err(RepositoryError::Forbidden.into());
    }
    Ok(tenant)
}

/// Every mutation locks the billing container before a resource container. This
/// also serializes organization-member removal against workspace membership edits.
pub(super) async fn load_account_scope(
    tx: &DatabaseTransaction,
    id: AccountId,
    lock: bool,
) -> Result<(Tenant, Account)> {
    let initial = account::Entity::find_by_id(id.0)
        .one(tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::NotFound)?;
    let tenant = load_tenant(tx, TenantId(initial.tenant_id), lock).await?;
    let mut query = account::Entity::find_by_id(id.0);
    if lock && tx.get_database_backend() == DbBackend::Postgres {
        query = query.lock_exclusive();
    }
    let account = account_from_model(
        query
            .one(tx)
            .await
            .map_err(map_error)?
            .ok_or(RepositoryError::NotFound)?,
    )?;
    if !account.is_active || account.tenant_id != tenant.id {
        return Err(RepositoryError::Forbidden.into());
    }
    match (tenant.kind, account.kind) {
        (TenantKind::Personal, AccountKind::Personal)
            if tenant.personal_user_id.is_some()
                && tenant.personal_user_id == account.personal_user_id => {}
        (TenantKind::Organization, AccountKind::Workspace)
            if tenant.personal_user_id.is_none() && account.personal_user_id.is_none() => {}
        _ => return Err(RepositoryError::Forbidden.into()),
    }
    Ok((tenant, account))
}

pub(super) async fn tenant_role(
    tx: &DatabaseTransaction,
    tenant: &Tenant,
    actor: &UserId,
) -> Result<MemberRole> {
    if tenant.kind == TenantKind::Personal && tenant.personal_user_id.as_ref() != Some(actor) {
        return Err(RepositoryError::Forbidden.into());
    }
    let member = tenant_member::Entity::find_by_id((tenant.id.0, actor.0))
        .one(tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::Forbidden)?;
    Ok(member.role.parse()?)
}

pub(super) async fn authorize_account(
    tx: &DatabaseTransaction,
    actor: &UserId,
    id: AccountId,
    lock: bool,
) -> Result<(Tenant, Account, MemberRole)> {
    let (tenant, account) = load_account_scope(tx, id, lock).await?;
    tenant_role(tx, &tenant, actor).await?;
    if account.kind == AccountKind::Personal && account.personal_user_id.as_ref() != Some(actor) {
        return Err(RepositoryError::Forbidden.into());
    }
    let member = account_member::Entity::find_by_id((id.0, actor.0))
        .one(tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::Forbidden)?;
    Ok((tenant, account, member.role.parse()?))
}

pub(super) fn ensure_can_manage(
    actor: MemberRole,
    current: Option<MemberRole>,
    requested: Option<MemberRole>,
) -> Result<()> {
    match actor {
        MemberRole::Owner => Ok(()),
        MemberRole::Admin
            if current.is_none_or(|role| role == MemberRole::Member)
                && requested.is_none_or(|role| role == MemberRole::Member) =>
        {
            Ok(())
        }
        _ => Err(RepositoryError::Forbidden.into()),
    }
}

pub(super) fn ensure_name(name: &str) -> Result<()> {
    if name.trim().is_empty() {
        return Err(RepositoryError::InvalidInput("name must not be blank").into());
    }
    Ok(())
}

pub(super) async fn ensure_other_tenant_owner(
    tx: &DatabaseTransaction,
    tenant: TenantId,
    target: &UserId,
) -> Result<()> {
    let other = tenant_member::Entity::find()
        .filter(tenant_member::Column::TenantId.eq(tenant.0))
        .filter(tenant_member::Column::UserId.ne(target.0))
        .filter(tenant_member::Column::Role.eq(MemberRole::Owner.as_str()))
        .one(tx)
        .await
        .map_err(map_error)?;
    if other.is_none() {
        return Err(RepositoryError::Conflict.into());
    }
    Ok(())
}

pub(super) async fn ensure_other_account_owner(
    tx: &DatabaseTransaction,
    account: AccountId,
    target: &UserId,
) -> Result<()> {
    let other = account_member::Entity::find()
        .filter(account_member::Column::AccountId.eq(account.0))
        .filter(account_member::Column::UserId.ne(target.0))
        .filter(account_member::Column::Role.eq(MemberRole::Owner.as_str()))
        .one(tx)
        .await
        .map_err(map_error)?;
    if other.is_none() {
        return Err(RepositoryError::Conflict.into());
    }
    Ok(())
}
