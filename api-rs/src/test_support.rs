//! Isolated database setup shared by HTTP and account authorization tests.

use std::sync::Arc;

use sea_orm::{ConnectOptions, ConnectionTrait, Database, DatabaseConnection, Schema};

use crate::entities::{account, account_member, item, tenant, tenant_member};

pub async fn database() -> Arc<DatabaseConnection> {
    let mut options = ConnectOptions::new("sqlite::memory:");
    options.max_connections(1);
    let db = Database::connect(options).await.unwrap();
    db.execute_unprepared("ATTACH DATABASE ':memory:' AS public")
        .await
        .unwrap();
    let schema = Schema::new(db.get_database_backend());
    for statement in [
        crate::repositories::orm::user::user_table_for_tests(db.get_database_backend()),
        schema.create_table_from_entity(tenant::Entity),
        schema.create_table_from_entity(account::Entity),
        schema.create_table_from_entity(tenant_member::Entity),
        schema.create_table_from_entity(account_member::Entity),
        schema.create_table_from_entity(item::Entity),
    ] {
        db.execute(&statement).await.unwrap();
    }
    Arc::new(db)
}
