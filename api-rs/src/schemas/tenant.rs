use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

use super::account::MemberRole;
use crate::models::tenant as domain;

#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum TenantKind {
    Personal,
    Organization,
}

impl From<domain::TenantKind> for TenantKind {
    fn from(kind: domain::TenantKind) -> Self {
        match kind {
            domain::TenantKind::Personal => Self::Personal,
            domain::TenantKind::Organization => Self::Organization,
        }
    }
}

/// 创建组织计费单元；个人计费单元由用户注册流程自动创建。
#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateTenant {
    pub name: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TenantResponse {
    pub id: Uuid,
    pub name: String,
    pub kind: TenantKind,
    pub personal_user_id: Option<Uuid>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
}

impl From<domain::Tenant> for TenantResponse {
    fn from(tenant: domain::Tenant) -> Self {
        Self {
            id: tenant.id.0,
            name: tenant.name,
            kind: tenant.kind.into(),
            personal_user_id: tenant.personal_user_id.map(|user| user.0),
            is_active: tenant.is_active,
            created_at: tenant.created_at,
        }
    }
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TenantMemberResponse {
    pub tenant_id: Uuid,
    pub user_id: Uuid,
    pub role: MemberRole,
    pub created_at: DateTime<Utc>,
}

impl From<domain::TenantMember> for TenantMemberResponse {
    fn from(member: domain::TenantMember) -> Self {
        Self {
            tenant_id: member.tenant_id.0,
            user_id: member.user_id.0,
            role: member.role.into(),
            created_at: member.created_at,
        }
    }
}
