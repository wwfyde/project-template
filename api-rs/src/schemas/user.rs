use crate::models::user::{User, UserId};
use chrono::{DateTime, FixedOffset};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;
use validator::Validate;
// the input to our `create_user` handler
#[derive(Debug, Deserialize, Validate, ToSchema)]
pub struct CreateUser {
    /// 用户名
    pub username: String,
    /// 密码
    pub password: String,
    /// 邮箱
    pub email: String,
}

// the output to our `create_user` handler
#[derive(Serialize, ToSchema)]
pub struct UserResponse {
    pub id: Uuid,
    pub username: String,
    // pub password: String,
    pub email: Option<String>,
    pub created_at: DateTime<FixedOffset>,
    pub updated_at: Option<DateTime<FixedOffset>>,
}

impl From<User> for UserResponse {
    fn from(user: User) -> Self {
        Self {
            id: user.id.0,
            username: user.username.unwrap_or_default(),
            // password: user.hashed_password.unwrap_or_default(),
            email: user.email,
            created_at: user.created_at.into(),
            updated_at: user.updated_at.map(|dt| dt.into()),
        }
    }
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct PageParams {
    /// Starts at 1
    // #[serde(default = "default_page")]
    pub page: u32,
    /// 1..=100
    // #[serde(default = "default_per_page")]
    pub per_page: u32,
    pub q: Option<String>,
    pub status: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct Tag {
    pub key: String,
    pub label: String,
}
#[derive(Debug, Serialize, ToSchema)]
// #[serde(rename_all = "camelCase")]
pub struct CurrentUser {
    pub name: String,
    pub avatar: String,
    pub user_id: UserId,
    pub email: String,
    pub signature: String,
    pub title: String,
    pub group: String,
    pub tags: Vec<Tag>,
    pub notify_count: u32,
    pub unread_count: u32,
    pub country: Option<String>,
    pub access: Option<String>,
    pub geographic: Option<Geographic>,
    pub address: Option<String>,
    pub phone: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct Geographic {
    pub province: GeographicItem,
    pub city: GeographicItem,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct GeographicItem {
    pub label: String,
    pub key: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    use utoipa::OpenApi;

    #[derive(OpenApi)]
    #[openapi(components(schemas(CurrentUser)))]
    struct UserSchemaDoc;

    #[test]
    fn nested_user_types_have_complete_openapi_schemas() {
        let document = serde_json::to_value(UserSchemaDoc::openapi()).expect("serialize OpenAPI");
        let schemas = &document["components"]["schemas"];
        for name in [
            "CurrentUser",
            "UserId",
            "Tag",
            "Geographic",
            "GeographicItem",
        ] {
            assert!(schemas.get(name).is_some(), "missing schema {name}");
        }
        assert_eq!(schemas["UserId"]["type"], "string");
        assert_eq!(schemas["UserId"]["format"], "uuid");
    }
}
