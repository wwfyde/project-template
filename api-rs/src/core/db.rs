use std::time::Duration;

use sea_orm::{ConnectOptions, Database, DatabaseConnection, DbErr};
use url::Url;

pub async fn connect(url: Url) -> Result<DatabaseConnection, DbErr> {
    let mut options = ConnectOptions::new(url);
    options
        .max_connections(10)
        .connect_timeout(Duration::from_secs(10))
        .acquire_timeout(Duration::from_secs(10))
        .sqlx_logging(false);
    Database::connect(options).await
}
