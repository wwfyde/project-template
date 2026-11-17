mod app;
pub mod config;
mod error;
pub mod handlers;
pub mod repositories;
pub mod routes;
pub mod schemas;
pub mod services;
mod state;

pub mod entities;

mod core;
mod middleware;
pub mod models;
mod telemetry;
pub mod utils;

#[cfg(test)]
mod test_support;

use crate::state::AppState;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    app::run().await
}
