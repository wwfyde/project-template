use crate::models::Locale;
use crate::models::user::{Uid, User, UserId};
use chrono::{DateTime, FixedOffset};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;
use validator::Validate;
// the input to our `create_user` handler
#[derive(Debug, Deserialize, Validate, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateUser {
    /// 用户名
    pub username: String,
    /// 密码
    pub password: String,
    /// 邮箱
    pub email: String,
    /// 昵称，可省略；不要求唯一。
    pub nickname: Option<String>,
    /// 界面语言，省略时使用 zh-CN。
    #[serde(default)]
    #[schema(default = "zh-CN")]
    pub locale: Locale,
}

// the output to our `create_user` handler
#[derive(Serialize, ToSchema)]
pub struct UserResponse {
    pub id: Uuid,
    /// 数据库分配的只读数字身份。
    #[schema(read_only)]
    pub uid: Uid,
    pub username: String,
    pub nickname: Option<String>,
    pub locale: Locale,
    pub email: Option<String>,
    pub created_at: DateTime<FixedOffset>,
    pub updated_at: Option<DateTime<FixedOffset>>,
}

impl From<User> for UserResponse {
    fn from(user: User) -> Self {
        Self {
            id: user.id.0,
            uid: user.uid,
            username: user.username.unwrap_or_default(),
            nickname: user.nickname,
            locale: user.locale,
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
    #[openapi(components(schemas(CurrentUser, CreateUser, UserResponse)))]
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
        assert!(schemas["UserResponse"]["properties"].get("uid").is_some());
        assert!(
            schemas["UserResponse"]["properties"]
                .get("nickname")
                .is_some()
        );
        assert!(
            schemas["UserResponse"]["properties"]
                .get("locale")
                .is_some()
        );
        assert!(schemas["CreateUser"]["properties"].get("uid").is_none());
        assert_eq!(schemas["Uid"]["maximum"], i64::MAX);
        assert_eq!(
            schemas["Locale"]["enum"],
            serde_json::json!(["zh-CN", "en-US", "ja-JP"])
        );
    }

    #[test]
    fn create_user_defaults_profile_fields_and_rejects_assigned_uid_or_unknown_locale() {
        let payload = serde_json::json!({
            "username": "alice", "password": "test-password", "email": "alice@example.com"
        });
        let user: CreateUser = serde_json::from_value(payload.clone()).unwrap();
        assert_eq!(user.nickname, None);
        assert_eq!(user.locale, Locale::ZhCn);

        let mut explicit = payload.clone();
        explicit["nickname"] = serde_json::json!("Alice");
        explicit["locale"] = serde_json::json!("ja-JP");
        let user: CreateUser = serde_json::from_value(explicit.clone()).unwrap();
        assert_eq!(user.nickname.as_deref(), Some("Alice"));
        assert_eq!(user.locale, Locale::JaJp);
        explicit["locale"] = serde_json::json!("unsupported");
        assert!(serde_json::from_value::<CreateUser>(explicit).is_err());

        let mut assigned_uid = payload;
        assigned_uid["uid"] = serde_json::json!(123);
        assert!(serde_json::from_value::<CreateUser>(assigned_uid).is_err());
    }
}
