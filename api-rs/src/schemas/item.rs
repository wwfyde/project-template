use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;
use uuid::Uuid;

#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateItem {
    pub title: String,
    pub description: Option<String>,
    pub description2: Option<String>,
    pub config: Value,
    pub owner_id: Uuid,
}

/// PUT replaces every editable field; omitted or null descriptions clear their values.
#[derive(Debug, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct UpdateItem {
    pub title: String,
    pub description: Option<String>,
    pub description2: Option<String>,
    pub config: Value,
    pub owner_id: Uuid,
}

#[derive(Debug, Serialize, Deserialize, Clone, ToSchema)]
pub struct Item {
    pub id: Uuid,
    pub title: String,
    pub description: Option<String>,
    pub description2: Option<String>,
    pub config: Value,
    pub owner_id: Uuid,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

impl From<crate::entities::item::Model> for Item {
    fn from(item: crate::entities::item::Model) -> Self {
        Self {
            id: item.id,
            title: item.title.unwrap_or_default(),
            description: item.description,
            description2: item.description2,
            config: item.config,
            owner_id: item.owner_id,
            created_at: item.created_at.with_timezone(&Utc),
            updated_at: item.updated_at.map(|dt| dt.with_timezone(&Utc)),
        }
    }
}
