use crate::AppState;
use crate::error::AuthError;
use crate::models::account::AccountAccess;
use crate::models::shared::AccountId;
use crate::models::user::UserId;
use crate::repositories::orm::account::SeaOrmAccountRepository;
use crate::services::account::AccountService;
use axum::{
    Json,
    extract::FromRequestParts,
    http::{HeaderMap, StatusCode, header, request::Parts},
};
use std::sync::Arc;
use uuid::Uuid;

pub struct ApiKeyAuth;

impl FromRequestParts<Arc<AppState>> for ApiKeyAuth {
    type Rejection = (StatusCode, Json<AuthError>);

    async fn from_request_parts(
        parts: &mut Parts,
        state: &Arc<AppState>,
    ) -> Result<Self, Self::Rejection> {
        state.auth.verify_api_key(&parts.headers, true)?;
        Ok(Self)
    }
}

pub struct AuthUser {
    pub user_id: Uuid,
}

impl FromRequestParts<Arc<AppState>> for AuthUser {
    type Rejection = (StatusCode, Json<AuthError>);

    async fn from_request_parts(
        parts: &mut Parts,
        state: &Arc<AppState>,
    ) -> Result<Self, Self::Rejection> {
        ApiKeyAuth::from_request_parts(parts, state).await?;

        let token = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|header| header.to_str().ok())
            .and_then(bearer_token)
            .ok_or_else(|| {
                (
                    StatusCode::UNAUTHORIZED,
                    Json(AuthError::Unauthorized(
                        "Missing or invalid bearer token".to_string(),
                    )),
                )
            })?;
        let claims = state
            .auth
            .verify_access_token(token)
            .map_err(|error| (StatusCode::UNAUTHORIZED, Json(error)))?;

        let user_id = Uuid::parse_str(&claims.sub).map_err(|_| {
            (
                StatusCode::UNAUTHORIZED,
                Json(AuthError::Unauthorized("Invalid user identity".to_string())),
            )
        })?;
        Ok(AuthUser { user_id })
    }
}

/// A current, server-verified resource boundary. The tenant is resolved from the
/// account; request headers never independently assign a billing tenant.
pub struct AccountContext(pub AccountAccess);

impl FromRequestParts<Arc<AppState>> for AccountContext {
    type Rejection = StatusCode;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &Arc<AppState>,
    ) -> Result<Self, Self::Rejection> {
        let user = AuthUser::from_request_parts(parts, state)
            .await
            .map_err(|(status, _)| status)?;
        let selected = selected_account(&parts.headers)?;
        let service = AccountService::new(Arc::new(SeaOrmAccountRepository::new(state.db.clone())));
        let access = service
            .resolve_account(UserId(user.user_id), selected)
            .await?;
        Ok(Self(access))
    }
}

fn selected_account(headers: &HeaderMap) -> Result<Option<AccountId>, StatusCode> {
    let mut values = headers.get_all("x-account-id").iter();
    let Some(value) = values.next() else {
        return Ok(None);
    };
    if values.next().is_some() {
        return Err(StatusCode::BAD_REQUEST);
    }
    let value = value.to_str().map_err(|_| StatusCode::BAD_REQUEST)?;
    let id = Uuid::parse_str(value).map_err(|_| StatusCode::BAD_REQUEST)?;
    Ok(Some(AccountId(id)))
}

fn bearer_token(value: &str) -> Option<&str> {
    let (scheme, token) = value.split_once(' ')?;
    if scheme.eq_ignore_ascii_case("bearer")
        && !token.is_empty()
        && !token.chars().any(char::is_whitespace)
    {
        Some(token)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::{bearer_token, selected_account};
    use axum::http::{HeaderMap, HeaderValue, StatusCode};
    use uuid::Uuid;

    #[test]
    fn bearer_scheme_is_case_insensitive() {
        assert_eq!(bearer_token("Bearer token"), Some("token"));
        assert_eq!(bearer_token("bearer token"), Some("token"));
        assert_eq!(bearer_token("BEARER token"), Some("token"));
    }

    #[test]
    fn invalid_authorization_headers_are_rejected() {
        for header in [
            "Bearer",
            "Bearer ",
            "Basic token",
            "Bearer token extra",
            "Bearer  token",
        ] {
            assert_eq!(bearer_token(header), None);
        }
    }

    #[test]
    fn account_selector_rejects_ambiguous_or_invalid_headers() {
        let mut headers = HeaderMap::new();
        assert_eq!(selected_account(&headers).unwrap(), None);
        let id = Uuid::now_v7();
        headers.insert(
            "x-account-id",
            HeaderValue::from_str(&id.to_string()).unwrap(),
        );
        assert_eq!(selected_account(&headers).unwrap().unwrap().0, id);
        headers.append(
            "x-account-id",
            HeaderValue::from_str(&id.to_string()).unwrap(),
        );
        assert_eq!(selected_account(&headers), Err(StatusCode::BAD_REQUEST));
        for value in ["", "not-a-uuid"] {
            headers.insert("x-account-id", HeaderValue::from_static(value));
            assert_eq!(selected_account(&headers), Err(StatusCode::BAD_REQUEST));
        }
    }
}
