use anyhow::Result;
use chrono::Utc;
use sea_orm::sea_query::OnConflict;
use sea_orm::{
    ColumnTrait, ConnectionTrait, DatabaseConnection, DbBackend, EntityTrait, QueryFilter,
    QueryOrder, QuerySelect, Set, TransactionTrait,
};

use crate::entities::{account, account_member, tenant_member};
use crate::models::account::{AccountKind, AccountMember, MemberRole};
use crate::models::shared::AccountId;
use crate::models::tenant::{TenantId, TenantKind, TenantMember};
use crate::models::user::UserId;
use crate::repositories::RepositoryError;

use super::super::map_error;
use super::helpers::*;

pub(super) async fn tenant_members(
    db: &DatabaseConnection,
    actor: UserId,
    id: TenantId,
) -> Result<Vec<TenantMember>> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    let tenant = load_tenant(&tx, id, false).await?;
    tenant_role(&tx, &tenant, &actor).await?;
    let members = tenant_member::Entity::find()
        .filter(tenant_member::Column::TenantId.eq(id.0))
        .order_by_asc(tenant_member::Column::CreatedAt)
        .order_by_asc(tenant_member::Column::UserId)
        .all(&tx)
        .await
        .map_err(map_error)?
        .into_iter()
        .map(tenant_member_from_model)
        .collect::<Result<Vec<_>>>()?;
    tx.commit().await.map_err(map_error)?;
    Ok(members)
}

pub(super) async fn account_members(
    db: &DatabaseConnection,
    actor: UserId,
    id: AccountId,
) -> Result<Vec<AccountMember>> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    authorize_account(&tx, &actor, id, false).await?;
    let members = account_member::Entity::find()
        .filter(account_member::Column::AccountId.eq(id.0))
        .order_by_asc(account_member::Column::CreatedAt)
        .order_by_asc(account_member::Column::UserId)
        .all(&tx)
        .await
        .map_err(map_error)?
        .into_iter()
        .map(account_member_from_model)
        .collect::<Result<Vec<_>>>()?;
    tx.commit().await.map_err(map_error)?;
    Ok(members)
}

pub(super) async fn put_tenant_member(
    db: &DatabaseConnection,
    actor: UserId,
    id: TenantId,
    target: UserId,
    role: MemberRole,
) -> Result<TenantMember> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    let tenant = load_tenant(&tx, id, true).await?;
    let actor_role = tenant_role(&tx, &tenant, &actor).await?;
    if tenant.kind != TenantKind::Organization {
        return Err(RepositoryError::Forbidden.into());
    }
    let current = tenant_member::Entity::find_by_id((id.0, target.0))
        .one(&tx)
        .await
        .map_err(map_error)?;
    let current_role = current
        .as_ref()
        .map(|member| member.role.parse::<MemberRole>())
        .transpose()?;
    ensure_can_manage(actor_role, current_role, Some(role))?;
    ensure_active_user(&tx, &target).await?;
    if current_role == Some(MemberRole::Owner) && role != MemberRole::Owner {
        ensure_other_tenant_owner(&tx, id, &target).await?;
    }
    let result = tenant_member::Entity::insert(tenant_member::ActiveModel {
        tenant_id: Set(id.0),
        user_id: Set(target.0),
        role: Set(role.as_str().to_owned()),
        created_at: Set(Utc::now().into()),
    })
    .on_conflict(
        OnConflict::columns([
            tenant_member::Column::TenantId,
            tenant_member::Column::UserId,
        ])
        .update_column(tenant_member::Column::Role)
        .to_owned(),
    )
    .exec_with_returning(&tx)
    .await
    .map_err(map_error)?;
    let member = tenant_member_from_model(result)?;
    tx.commit().await.map_err(map_error)?;
    Ok(member)
}

pub(super) async fn put_account_member(
    db: &DatabaseConnection,
    actor: UserId,
    id: AccountId,
    target: UserId,
    role: MemberRole,
) -> Result<AccountMember> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    let (tenant, account, actor_role) = authorize_account(&tx, &actor, id, true).await?;
    if account.kind != AccountKind::Workspace {
        return Err(RepositoryError::Forbidden.into());
    }
    let current = account_member::Entity::find_by_id((id.0, target.0))
        .one(&tx)
        .await
        .map_err(map_error)?;
    let current_role = current
        .as_ref()
        .map(|member| member.role.parse::<MemberRole>())
        .transpose()?;
    ensure_can_manage(actor_role, current_role, Some(role))?;
    ensure_active_user(&tx, &target).await?;
    // Account membership alone must never create organization membership.
    tenant_role(&tx, &tenant, &target).await?;
    if current_role == Some(MemberRole::Owner) && role != MemberRole::Owner {
        ensure_other_account_owner(&tx, id, &target).await?;
    }
    let result = account_member::Entity::insert(account_member::ActiveModel {
        account_id: Set(id.0),
        user_id: Set(target.0),
        role: Set(role.as_str().to_owned()),
        created_at: Set(Utc::now().into()),
    })
    .on_conflict(
        OnConflict::columns([
            account_member::Column::AccountId,
            account_member::Column::UserId,
        ])
        .update_column(account_member::Column::Role)
        .to_owned(),
    )
    .exec_with_returning(&tx)
    .await
    .map_err(map_error)?;
    let member = account_member_from_model(result)?;
    tx.commit().await.map_err(map_error)?;
    Ok(member)
}

pub(super) async fn remove_account_member(
    db: &DatabaseConnection,
    actor: UserId,
    id: AccountId,
    target: UserId,
) -> Result<()> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    let (_, account, actor_role) = authorize_account(&tx, &actor, id, true).await?;
    if account.kind != AccountKind::Workspace {
        return Err(RepositoryError::Forbidden.into());
    }
    let current = account_member::Entity::find_by_id((id.0, target.0))
        .one(&tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::NotFound)?;
    let role = current.role.parse::<MemberRole>()?;
    ensure_can_manage(actor_role, Some(role), None)?;
    if role == MemberRole::Owner {
        ensure_other_account_owner(&tx, id, &target).await?;
    }
    account_member::Entity::delete_by_id((id.0, target.0))
        .exec(&tx)
        .await
        .map_err(map_error)?;
    tx.commit().await.map_err(map_error)?;
    Ok(())
}

pub(super) async fn remove_tenant_member(
    db: &DatabaseConnection,
    actor: UserId,
    id: TenantId,
    target: UserId,
) -> Result<()> {
    let tx = db.begin().await.map_err(map_error)?;
    ensure_active_user(&tx, &actor).await?;
    let tenant = load_tenant(&tx, id, true).await?;
    let actor_role = tenant_role(&tx, &tenant, &actor).await?;
    if tenant.kind != TenantKind::Organization {
        return Err(RepositoryError::Forbidden.into());
    }
    let current = tenant_member::Entity::find_by_id((id.0, target.0))
        .one(&tx)
        .await
        .map_err(map_error)?
        .ok_or(RepositoryError::NotFound)?;
    let role = current.role.parse::<MemberRole>()?;
    ensure_can_manage(actor_role, Some(role), None)?;
    if role == MemberRole::Owner {
        ensure_other_tenant_owner(&tx, id, &target).await?;
    }

    let mut query = account::Entity::find()
        .filter(account::Column::TenantId.eq(id.0))
        .order_by_asc(account::Column::Id);
    if tx.get_database_backend() == DbBackend::Postgres {
        query = query.lock_exclusive();
    }
    let accounts = query.all(&tx).await.map_err(map_error)?;
    for account in &accounts {
        if let Some(member) = account_member::Entity::find_by_id((account.id, target.0))
            .one(&tx)
            .await
            .map_err(map_error)?
        {
            let account_role = member.role.parse::<MemberRole>()?;
            // Organization-level removal must not let an Admin bypass a
            // workspace's protected Admin/Owner roles through cascading deletion.
            ensure_can_manage(actor_role, Some(account_role), None)?;
            if account_role == MemberRole::Owner {
                ensure_other_account_owner(&tx, AccountId(account.id), &target).await?;
            }
        }
    }
    // Removing the billing membership also revokes every workspace membership in
    // this tenant, while preserving the user's memberships in other tenants.
    let account_ids = accounts
        .into_iter()
        .map(|account| account.id)
        .collect::<Vec<_>>();
    if !account_ids.is_empty() {
        account_member::Entity::delete_many()
            .filter(account_member::Column::AccountId.is_in(account_ids))
            .filter(account_member::Column::UserId.eq(target.0))
            .exec(&tx)
            .await
            .map_err(map_error)?;
    }
    tenant_member::Entity::delete_by_id((id.0, target.0))
        .exec(&tx)
        .await
        .map_err(map_error)?;
    tx.commit().await.map_err(map_error)?;
    Ok(())
}
