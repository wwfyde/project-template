use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

use crate::models::account as domain;

#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum AccountKind {
    Personal,
    Workspace,
}

impl From<domain::AccountKind> for AccountKind {
    fn from(kind: domain::AccountKind) -> Self {
        match kind {
            domain::AccountKind::Personal => Self::Personal,
            domain::AccountKind::Workspace => Self::Workspace,
        }
    }
}

/// 角色只在对应的 tenant 或 account 成员关系内有效。
#[derive(Clone, Copy, Debug, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum MemberRole {
    Owner,
    Admin,
    Member,
}

impl From<domain::MemberRole> for MemberRole {
    fn from(role: domain::MemberRole) -> Self {
        match role {
            domain::MemberRole::Owner => Self::Owner,
            domain::MemberRole::Admin => Self::Admin,
            domain::MemberRole::Member => Self::Member,
        }
    }
}

impl From<MemberRole> for domain::MemberRole {
    fn from(role: MemberRole) -> Self {
        match role {
            MemberRole::Owner => Self::Owner,
            MemberRole::Admin => Self::Admin,
            MemberRole::Member => Self::Member,
        }
    }
}

#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateWorkspace {
    pub name: String,
}

#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct SetMemberRole {
    pub role: MemberRole,
}

/// 资源管理与隔离边界。所属 tenant 决定计费归属。
#[derive(Debug, Serialize, ToSchema)]
pub struct AccountResponse {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub name: String,
    pub kind: AccountKind,
    pub personal_user_id: Option<Uuid>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

impl From<domain::Account> for AccountResponse {
    fn from(account: domain::Account) -> Self {
        Self {
            id: account.id.0,
            tenant_id: account.tenant_id.0,
            name: account.name,
            kind: account.kind.into(),
            personal_user_id: account.personal_user_id.map(|user| user.0),
            is_active: account.is_active,
            created_at: account.created_at,
        }
    }
}

/// 当前请求的授权上下文；tenant_id 根据账户归属解析，不能由调用者覆盖。
#[derive(Debug, Serialize, ToSchema)]
pub struct AccountContextResponse {
    pub user_id: Uuid,
    pub account_id: Uuid,
    pub tenant_id: Uuid,
    pub role: MemberRole,
}

impl From<domain::AccountAccess> for AccountContextResponse {
    fn from(access: domain::AccountAccess) -> Self {
        Self {
            user_id: access.user_id.0,
            account_id: access.account_id.0,
            tenant_id: access.tenant_id.0,
            role: access.role.into(),
        }
    }
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AccountMemberResponse {
    pub account_id: Uuid,
    pub user_id: Uuid,
    pub role: MemberRole,
    pub created_at: DateTime<Utc>,
}

impl From<domain::AccountMember> for AccountMemberResponse {
    fn from(member: domain::AccountMember) -> Self {
        Self {
            account_id: member.account_id.0,
            user_id: member.user_id.0,
            role: member.role.into(),
            created_at: member.created_at,
        }
    }
}
