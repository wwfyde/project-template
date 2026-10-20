use crate::AppState;
use crate::error::AuthError;
use axum::{
    Json,
    extract::FromRequestParts,
    http::{StatusCode, header, request::Parts},
};
use std::sync::Arc;

pub struct AuthUser {
    pub username: String,
}

impl FromRequestParts<Arc<AppState>> for AuthUser {
    type Rejection = (StatusCode, Json<AuthError>);

    async fn from_request_parts(
        parts: &mut Parts,
        state: &Arc<AppState>,
    ) -> Result<Self, Self::Rejection> {
        state.auth.verify_api_key(&parts.headers, true)?;

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

        Ok(AuthUser {
            username: claims.sub,
        })
    }
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
    use super::bearer_token;

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
}
