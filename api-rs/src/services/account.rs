use std::sync::Arc;

use axum::http::StatusCode;

use crate::models::account::{Account, AccountAccess, AccountMember, MemberRole};
use crate::models::account_repository::AccountRepository;
use crate::models::shared::AccountId;
use crate::models::tenant::{Tenant, TenantId, TenantMember};
use crate::models::user::{User, UserId, UserWrite};
use crate::repositories::RepositoryError;

/// Coordinates account use cases through a transactional persistence port.
pub struct AccountService {
    repo: Arc<dyn AccountRepository>,
}

impl AccountService {
    pub fn new(repo: Arc<dyn AccountRepository>) -> Self {
        Self { repo }
    }

    pub async fn register_user(&self, input: &UserWrite) -> Result<User, StatusCode> {
        self.repo.register_user(input).await.map_err(map_error)
    }

    pub async fn list_tenants(&self, actor: UserId) -> Result<Vec<Tenant>, StatusCode> {
        self.repo.list_tenants(actor).await.map_err(map_error)
    }

    pub async fn create_tenant(&self, actor: UserId, name: &str) -> Result<Tenant, StatusCode> {
        self.repo
            .create_tenant(actor, name)
            .await
            .map_err(map_error)
    }

    pub async fn list_accounts(&self, actor: UserId) -> Result<Vec<Account>, StatusCode> {
        self.repo.list_accounts(actor).await.map_err(map_error)
    }

    pub async fn get_account(
        &self,
        actor: UserId,
        account: AccountId,
    ) -> Result<Account, StatusCode> {
        self.repo
            .get_account(actor, account)
            .await
            .map_err(map_error)
    }

    pub async fn resolve_account(
        &self,
        actor: UserId,
        selected: Option<AccountId>,
    ) -> Result<AccountAccess, StatusCode> {
        self.repo
            .resolve_account(actor, selected)
            .await
            .map_err(map_error)
    }

    pub async fn create_workspace(
        &self,
        actor: UserId,
        tenant: TenantId,
        name: &str,
    ) -> Result<Account, StatusCode> {
        self.repo
            .create_workspace(actor, tenant, name)
            .await
            .map_err(map_error)
    }

    pub async fn tenant_members(
        &self,
        actor: UserId,
        tenant: TenantId,
    ) -> Result<Vec<TenantMember>, StatusCode> {
        self.repo
            .tenant_members(actor, tenant)
            .await
            .map_err(map_error)
    }

    pub async fn put_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
        role: MemberRole,
    ) -> Result<TenantMember, StatusCode> {
        self.repo
            .put_tenant_member(actor, tenant, target, role)
            .await
            .map_err(map_error)
    }

    pub async fn remove_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
    ) -> Result<(), StatusCode> {
        self.repo
            .remove_tenant_member(actor, tenant, target)
            .await
            .map_err(map_error)
    }

    pub async fn account_members(
        &self,
        actor: UserId,
        account: AccountId,
    ) -> Result<Vec<AccountMember>, StatusCode> {
        self.repo
            .account_members(actor, account)
            .await
            .map_err(map_error)
    }

    pub async fn put_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
        role: MemberRole,
    ) -> Result<AccountMember, StatusCode> {
        self.repo
            .put_account_member(actor, account, target, role)
            .await
            .map_err(map_error)
    }

    pub async fn remove_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
    ) -> Result<(), StatusCode> {
        self.repo
            .remove_account_member(actor, account, target)
            .await
            .map_err(map_error)
    }
}

fn map_error(error: anyhow::Error) -> StatusCode {
    match error.downcast_ref::<RepositoryError>() {
        Some(RepositoryError::NotFound) => StatusCode::NOT_FOUND,
        Some(RepositoryError::Forbidden) => StatusCode::FORBIDDEN,
        Some(RepositoryError::Conflict) => StatusCode::CONFLICT,
        Some(RepositoryError::InvalidInput(_)) => StatusCode::BAD_REQUEST,
        None => {
            tracing::error!(?error, "account operation failed");
            StatusCode::INTERNAL_SERVER_ERROR
        }
    }
}
