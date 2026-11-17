//! A tenant is the billing and organization boundary above resource accounts.

use chrono::{DateTime, Utc};
use std::str::FromStr;
use uuid::Uuid;

use super::account::MemberRole;
use super::shared::{DomainError, DomainResult, require_non_blank};
use super::user::UserId;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct TenantId(pub Uuid);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TenantKind {
    Personal,
    Organization,
}

impl TenantKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Personal => "personal",
            Self::Organization => "organization",
        }
    }
}

impl FromStr for TenantKind {
    type Err = DomainError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "personal" => Ok(Self::Personal),
            "organization" => Ok(Self::Organization),
            _ => Err(DomainError::InvalidValue {
                field: "tenant_kind",
                reason: "must be personal or organization",
            }),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Tenant {
    pub id: TenantId,
    pub name: String,
    pub kind: TenantKind,
    pub personal_user_id: Option<UserId>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

impl Tenant {
    pub fn personal(
        id: TenantId,
        user_id: UserId,
        name: impl Into<String>,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        let name = name.into();
        require_non_blank("tenant_name", &name)?;
        Ok(Self {
            id,
            name,
            kind: TenantKind::Personal,
            personal_user_id: Some(user_id),
            is_active: true,
            created_at,
        })
    }

    pub fn organization(
        id: TenantId,
        name: impl Into<String>,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        let name = name.into();
        require_non_blank("tenant_name", &name)?;
        Ok(Self {
            id,
            name,
            kind: TenantKind::Organization,
            personal_user_id: None,
            is_active: true,
            created_at,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TenantMember {
    pub tenant_id: TenantId,
    pub user_id: UserId,
    pub role: MemberRole,
    pub created_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn billing_tenants_have_explicit_kinds_and_reject_blank_names() {
        let at = Utc::now();
        let user = UserId(Uuid::now_v7());
        let personal =
            Tenant::personal(TenantId(Uuid::now_v7()), user.clone(), "Personal", at).unwrap();
        let organization = Tenant::organization(TenantId(Uuid::now_v7()), "Company", at).unwrap();
        assert_eq!(personal.personal_user_id, Some(user.clone()));
        assert_eq!(organization.personal_user_id, None);
        assert!(Tenant::personal(TenantId(Uuid::now_v7()), user, " ", at).is_err());
        assert!(Tenant::organization(TenantId(Uuid::now_v7()), "\n", at).is_err());
        assert!("workspace".parse::<TenantKind>().is_err());
        assert!("billing_admin".parse::<MemberRole>().is_err());
    }
}
