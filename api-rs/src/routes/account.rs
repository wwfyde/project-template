use std::sync::Arc;

use axum::Router;
use axum::routing::{get, put};

use crate::AppState;
use crate::handlers::{account, tenant};

pub fn account_routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/accounts", get(account::list_accounts))
        .route("/accounts/current", get(account::current_account))
        .route("/accounts/{account_id}", get(account::get_account))
        .route("/accounts/{account_id}/members", get(account::list_members))
        .route(
            "/accounts/{account_id}/members/{user_id}",
            put(account::put_member).delete(account::remove_member),
        )
        .route(
            "/tenants",
            get(tenant::list_tenants).post(tenant::create_tenant),
        )
        .route(
            "/tenants/{tenant_id}/accounts",
            axum::routing::post(account::create_workspace),
        )
        .route("/tenants/{tenant_id}/members", get(tenant::list_members))
        .route(
            "/tenants/{tenant_id}/members/{user_id}",
            put(tenant::put_member).delete(tenant::remove_member),
        )
}

#[cfg(test)]
mod tests;
