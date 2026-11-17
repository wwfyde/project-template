//! Application-facing persistence port for atomic registration and membership changes.

use anyhow::Result;
use async_trait::async_trait;

use super::account::{Account, AccountAccess, AccountMember, MemberRole};
use super::shared::AccountId;
use super::tenant::{Tenant, TenantId, TenantMember};
use super::user::{User, UserId, UserWrite};

#[async_trait]
pub trait AccountRepository: Send + Sync {
    /// Create the identity and its personal billing/resource containers atomically.
    async fn register_user(&self, input: &UserWrite) -> Result<User>;
    async fn list_tenants(&self, actor: UserId) -> Result<Vec<Tenant>>;
    async fn create_tenant(&self, actor: UserId, name: &str) -> Result<Tenant>;
    async fn list_accounts(&self, actor: UserId) -> Result<Vec<Account>>;
    async fn get_account(&self, actor: UserId, account: AccountId) -> Result<Account>;
    /// Omitted selection resolves the actor's personal account, never an arbitrary membership.
    async fn resolve_account(
        &self,
        actor: UserId,
        selected: Option<AccountId>,
    ) -> Result<AccountAccess>;
    async fn create_workspace(
        &self,
        actor: UserId,
        tenant: TenantId,
        name: &str,
    ) -> Result<Account>;
    async fn tenant_members(&self, actor: UserId, tenant: TenantId) -> Result<Vec<TenantMember>>;
    async fn put_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
        role: MemberRole,
    ) -> Result<TenantMember>;
    async fn remove_tenant_member(
        &self,
        actor: UserId,
        tenant: TenantId,
        target: UserId,
    ) -> Result<()>;
    async fn account_members(
        &self,
        actor: UserId,
        account: AccountId,
    ) -> Result<Vec<AccountMember>>;
    async fn put_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
        role: MemberRole,
    ) -> Result<AccountMember>;
    async fn remove_account_member(
        &self,
        actor: UserId,
        account: AccountId,
        target: UserId,
    ) -> Result<()>;
}
