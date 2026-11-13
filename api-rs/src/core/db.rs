use std::time::Duration;

use sea_orm::{ConnectOptions, Database, DatabaseConnection, DbErr, TransactionTrait};
use url::Url;

use crate::entities;

pub async fn connect(url: Url, pool_size: u32) -> Result<DatabaseConnection, DbErr> {
    let mut options = ConnectOptions::new(url);
    options
        .max_connections(pool_size)
        .connect_timeout(Duration::from_secs(10))
        .acquire_timeout(Duration::from_secs(10))
        .sqlx_logging(false);
    Database::connect(options).await
}

/// Synchronize the PostgreSQL schema from application entities before serving requests.
/// Keep migration metadata tables outside the application's schema registry.
pub async fn sync_schema(db: &DatabaseConnection) -> Result<(), DbErr> {
    let transaction = db.begin().await?;
    db.get_schema_builder()
        .register(entities::author::Entity)
        .register(entities::book::Entity)
        .register(entities::book_author::Entity)
        .register(entities::course::Entity)
        .register(entities::item::Entity)
        .register(entities::llm::Entity)
        .register(entities::order::Entity)
        .register(entities::student::Entity)
        .register(entities::student_course::Entity)
        .register(entities::todo::Entity)
        .register(entities::user::Entity)
        .sync(&transaction)
        .await?;
    transaction.commit().await
}

#[cfg(test)]
mod tests;
