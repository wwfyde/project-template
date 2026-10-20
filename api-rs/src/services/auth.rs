use crate::entities::{user, user::Entity as User};
use crate::error::AuthError;
use crate::utils::security::verify_password;
use axum::Json;
use axum::http::{HeaderMap, StatusCode};
use chrono::{Duration, Utc};
use jsonwebtoken::{EncodingKey, Header, encode};
use sea_orm::{DatabaseConnection, EntityTrait, QueryFilter};
use serde::{Deserialize, Serialize};

#[derive(Clone)]
pub struct AuthService {
    pub api_key: String,
    pub jwt_secret: String,
    pub access_token_expire_days: i64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub exp: usize,
}

impl AuthService {
    pub fn new(api_key: String, jwt_secret: String, access_token_expire_days: i64) -> Self {
        Self {
            api_key,
            jwt_secret,
            access_token_expire_days,
        }
    }

    /// 验证 API 密钥。
    pub fn verify_api_key(
        &self,
        headers: &HeaderMap,
        require_api_key: bool,
    ) -> Result<(), (StatusCode, Json<AuthError>)> {
        match headers.get("X-Api-Key") {
            Some(header) if header != self.api_key.as_str() => Err((
                StatusCode::UNAUTHORIZED,
                Json(AuthError::Unauthorized("无效的 API 密钥".to_string())),
            )),
            None if require_api_key => Err((
                StatusCode::UNAUTHORIZED,
                Json(AuthError::Unauthorized("缺少 API 密钥".to_string())),
            )),
            _ => Ok(()),
        }
    }

    pub async fn active_user_by_username(
        &self,
        db: &DatabaseConnection,
        username: &str,
    ) -> Result<user::Model, AuthError> {
        let user = User::find()
            .filter(user::COLUMN.username.eq(username))
            .one(db)
            .await
            .map_err(|error| {
                tracing::error!(%error, "failed to look up authenticated user");
                AuthError::InternalServerError
            })?;

        active_user(user)
    }

    pub async fn authenticate_user(
        &self,
        db: &DatabaseConnection,
        username: &str,
        password: &str,
    ) -> Result<user::Model, AuthError> {
        let user = self.active_user_by_username(db, username).await?;
        let hashed = user
            .hashed_password
            .clone()
            .ok_or_else(invalid_credentials)?;
        let password = password.to_owned();
        let valid = tokio::task::spawn_blocking(move || verify_password(&password, &hashed))
            .await
            .map_err(|error| {
                tracing::error!(%error, "password verification task failed");
                AuthError::InternalServerError
            })?;

        if valid {
            Ok(user)
        } else {
            Err(invalid_credentials())
        }
    }

    pub fn access_token_lifetime_seconds(&self) -> Result<i64, AuthError> {
        self.access_token_expire_days
            .checked_mul(24 * 60 * 60)
            .filter(|seconds| *seconds > 0)
            .ok_or(AuthError::InternalServerError)
    }

    pub fn create_access_token(&self, username: &str) -> Result<String, AuthError> {
        let lifetime = self.access_token_lifetime_seconds()?;
        let expiration = Duration::try_seconds(lifetime)
            .and_then(|duration| Utc::now().checked_add_signed(duration))
            .and_then(|expiration| usize::try_from(expiration.timestamp()).ok())
            .ok_or(AuthError::InternalServerError)?;

        let claims = Claims {
            sub: username.to_owned(),
            exp: expiration,
        };

        encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(self.jwt_secret.as_bytes()),
        )
        .map_err(|error| {
            tracing::error!(%error, "failed to encode access token");
            AuthError::InternalServerError
        })
    }

    pub fn verify_access_token(&self, token: &str) -> Result<Claims, AuthError> {
        let token_data = jsonwebtoken::decode::<Claims>(
            token,
            &jsonwebtoken::DecodingKey::from_secret(self.jwt_secret.as_bytes()),
            &jsonwebtoken::Validation::default(),
        )
        .map_err(|_| AuthError::Unauthorized("Invalid or expired access token".to_string()))?;

        Ok(token_data.claims)
    }
}

fn invalid_credentials() -> AuthError {
    AuthError::Unauthorized("Incorrect username or password".to_string())
}

fn active_user(user: Option<user::Model>) -> Result<user::Model, AuthError> {
    user.filter(|user| user.is_active == Some(true))
        .ok_or_else(invalid_credentials)
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    fn auth_service(days: i64) -> AuthService {
        AuthService::new(
            "test-api-key".to_string(),
            "test-jwt-secret-with-at-least-32-characters".to_string(),
            days,
        )
    }

    #[test]
    fn access_token_lifetime_is_a_duration_in_seconds() {
        let service = auth_service(2);
        assert_eq!(service.access_token_lifetime_seconds().ok(), Some(172_800));
        let before = Utc::now().timestamp() as usize;
        let token = service
            .create_access_token("alice")
            .unwrap_or_else(|_| panic!("create token"));
        let claims = service
            .verify_access_token(&token)
            .unwrap_or_else(|_| panic!("verify token"));
        assert_eq!(claims.sub, "alice");
        assert!(
            (before + 172_800..=Utc::now().timestamp() as usize + 172_800).contains(&claims.exp)
        );
    }

    #[test]
    fn invalid_lifetimes_are_rejected_without_panicking() {
        for days in [0, -1, i64::MAX, i64::MAX / 86_400] {
            assert!(auth_service(days).create_access_token("alice").is_err());
        }
    }

    #[test]
    fn invalid_tokens_are_rejected() {
        let service = auth_service(1);
        assert!(service.verify_access_token("invalid-token").is_err());
        let expired = encode(
            &Header::default(),
            &Claims {
                sub: "alice".to_string(),
                exp: (Utc::now().timestamp() - 120) as usize,
            },
            &EncodingKey::from_secret(service.jwt_secret.as_bytes()),
        )
        .expect("encode test token");
        assert!(service.verify_access_token(&expired).is_err());
        let other_service = AuthService::new(
            "test-api-key".to_string(),
            "different-secret".to_string(),
            1,
        );
        let token = service
            .create_access_token("alice")
            .unwrap_or_else(|_| panic!("create token"));
        assert!(other_service.verify_access_token(&token).is_err());
    }

    #[test]
    fn missing_or_disabled_users_cannot_authenticate() {
        assert!(active_user(None).is_err());
        for is_active in [None, Some(false), Some(true)] {
            let user = user::Model {
                id: Uuid::now_v7(),
                email: "alice@example.com".to_string(),
                username: Some("alice".to_string()),
                hashed_password: None,
                is_active,
                is_superuser: Some(false),
                created_at: Utc::now().into(),
                updated_at: None,
            };
            assert_eq!(active_user(Some(user)).is_ok(), is_active == Some(true));
        }
    }
}
