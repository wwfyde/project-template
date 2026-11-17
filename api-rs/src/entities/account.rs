use sea_orm::entity::prelude::*;
use serde::{Deserialize, Serialize};

#[sea_orm::model]
#[derive(Clone, Debug, PartialEq, Eq, DeriveEntityModel, Serialize, Deserialize)]
#[sea_orm(schema_name = "public", table_name = "account")]
pub struct Model {
    #[sea_orm(primary_key, auto_increment = false)]
    pub id: Uuid,
    pub tenant_id: Uuid,
    #[sea_orm(extra = "CHECK (length(trim(name)) > 0)")]
    pub name: String,
    #[sea_orm(
        extra = "CHECK ((kind = 'personal' AND personal_user_id IS NOT NULL) OR (kind = 'workspace' AND personal_user_id IS NULL))"
    )]
    pub kind: String,
    #[sea_orm(unique)]
    pub personal_user_id: Option<Uuid>,
    #[sea_orm(default_value = true)]
    pub is_active: bool,
    pub created_at: DateTimeWithTimeZone,
    #[sea_orm(
        belongs_to,
        from = "tenant_id",
        to = "id",
        on_update = "NoAction",
        on_delete = "Restrict"
    )]
    pub tenant: BelongsTo<super::tenant::Entity>,
    #[sea_orm(
        belongs_to,
        from = "personal_user_id",
        to = "id",
        on_update = "NoAction",
        on_delete = "Restrict"
    )]
    pub personal_user: BelongsTo<Option<super::user::Entity>>,
}

impl ActiveModelBehavior for ActiveModel {}
