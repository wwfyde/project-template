#[tokio::main]
async fn main() {
    sea_orm_migration::cli::run_cli(api_rs::migration::Migrator).await;
}
