//! Accounts are resource boundaries. A workspace is an account category, while
//! its parent tenant determines the billing attribution.

use chrono::{DateTime, Utc};
use std::str::FromStr;

use super::shared::{AccountId, DomainError, DomainResult, require_non_blank};
use super::tenant::{Tenant, TenantId, TenantKind};
use super::user::UserId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AccountKind {
    Personal,
    Workspace,
}

impl AccountKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Personal => "personal",
            Self::Workspace => "workspace",
        }
    }
}

impl FromStr for AccountKind {
    type Err = DomainError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "personal" => Ok(Self::Personal),
            "workspace" => Ok(Self::Workspace),
            _ => Err(DomainError::InvalidValue {
                field: "account_kind",
                reason: "must be personal or workspace",
            }),
        }
    }
}

/// A role is always scoped to a particular tenant or account membership.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemberRole {
    Owner,
    Admin,
    Member,
}

impl MemberRole {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Owner => "owner",
            Self::Admin => "admin",
            Self::Member => "member",
        }
    }

    pub const fn can_manage(self) -> bool {
        matches!(self, Self::Owner | Self::Admin)
    }
}

impl FromStr for MemberRole {
    type Err = DomainError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "owner" => Ok(Self::Owner),
            "admin" => Ok(Self::Admin),
            "member" => Ok(Self::Member),
            _ => Err(DomainError::InvalidValue {
                field: "member_role",
                reason: "must be owner, admin or member",
            }),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Account {
    pub id: AccountId,
    pub tenant_id: TenantId,
    pub name: String,
    pub kind: AccountKind,
    pub personal_user_id: Option<UserId>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

impl Account {
    pub fn personal(
        id: AccountId,
        tenant: &Tenant,
        user_id: UserId,
        name: impl Into<String>,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        if !tenant.is_active
            || tenant.kind != TenantKind::Personal
            || tenant.personal_user_id.as_ref() != Some(&user_id)
        {
            return Err(DomainError::InvalidValue {
                field: "tenant",
                reason: "personal accounts require the same user's active personal tenant",
            });
        }
        let name = name.into();
        require_non_blank("account_name", &name)?;
        Ok(Self {
            id,
            tenant_id: tenant.id,
            name,
            kind: AccountKind::Personal,
            personal_user_id: Some(user_id),
            is_active: true,
            created_at,
        })
    }

    pub fn workspace(
        id: AccountId,
        tenant: &Tenant,
        name: impl Into<String>,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        if !tenant.is_active
            || tenant.kind != TenantKind::Organization
            || tenant.personal_user_id.is_some()
        {
            return Err(DomainError::InvalidValue {
                field: "tenant",
                reason: "workspace accounts require an active organization tenant",
            });
        }
        let name = name.into();
        require_non_blank("account_name", &name)?;
        Ok(Self {
            id,
            tenant_id: tenant.id,
            name,
            kind: AccountKind::Workspace,
            personal_user_id: None,
            is_active: true,
            created_at,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountMember {
    pub account_id: AccountId,
    pub user_id: UserId,
    pub role: MemberRole,
    pub created_at: DateTime<Utc>,
}

/// A request-scoped authorization result. Resolve this from live memberships,
/// rather than accepting account, tenant or role claims from request bodies.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountAccess {
    pub user_id: UserId,
    pub account_id: AccountId,
    pub tenant_id: TenantId,
    pub role: MemberRole,
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn personal_accounts_pin_their_users_personal_tenant() {
        let at = Utc::now();
        let user = UserId(Uuid::now_v7());
        let tenant =
            Tenant::personal(TenantId(Uuid::now_v7()), user.clone(), "Personal", at).unwrap();
        let account = Account::personal(
            AccountId(Uuid::now_v7()),
            &tenant,
            user.clone(),
            "Personal",
            at,
        )
        .unwrap();
        assert_eq!(account.tenant_id, tenant.id);
        assert_eq!(account.personal_user_id, Some(user));
        assert_eq!(account.kind, AccountKind::Personal);
        assert!(
            Account::personal(
                AccountId(Uuid::now_v7()),
                &tenant,
                UserId(Uuid::now_v7()),
                "Other person's account",
                at,
            )
            .is_err()
        );
        assert!(Account::workspace(AccountId(Uuid::now_v7()), &tenant, "Team", at).is_err());
    }

    #[test]
    fn workspace_creation_requires_an_active_organization_and_a_name() {
        let at = Utc::now();
        let mut tenant = Tenant::organization(TenantId(Uuid::now_v7()), "Company", at).unwrap();
        let account =
            Account::workspace(AccountId(Uuid::now_v7()), &tenant, "Engineering", at).unwrap();
        assert_eq!(account.kind, AccountKind::Workspace);
        assert_eq!(account.personal_user_id, None);
        assert_eq!(account.tenant_id, tenant.id);
        assert!(Account::workspace(AccountId(Uuid::now_v7()), &tenant, " ", at).is_err());
        assert!(
            Account::personal(
                AccountId(Uuid::now_v7()),
                &tenant,
                UserId(Uuid::now_v7()),
                "Personal",
                at,
            )
            .is_err()
        );
        tenant.personal_user_id = Some(UserId(Uuid::now_v7()));
        assert!(Account::workspace(AccountId(Uuid::now_v7()), &tenant, "Another", at).is_err());
        tenant.personal_user_id = None;
        tenant.is_active = false;
        assert!(Account::workspace(AccountId(Uuid::now_v7()), &tenant, "Another", at).is_err());
    }
}
