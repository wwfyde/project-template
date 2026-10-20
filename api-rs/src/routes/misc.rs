/// Redirect to the API documentation
#[utoipa::path(
    get,
    path = "/root",
    tag = "default",
    responses(
        (status = 200, description = "JSON file", body = ())
    )
)]
pub async fn root() -> String {
    let name = "世界";
    format!("Hello, {}!", name)
}
