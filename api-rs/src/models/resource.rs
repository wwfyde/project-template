use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct ResourceId(pub Uuid);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct WorkspaceId(pub Uuid);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct ClassifierId(pub Uuid);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct DimensionId(pub Uuid);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Resource {
    pub id: ResourceId,
    pub workspace_id: WorkspaceId,

    // 物理目录关系
    pub parent_id: Option<ResourceId>,

    pub name: String,
    pub content: ResourceContent,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ResourceContent {
    Folder,

    File {
        storage_key: String,
        mime_type: Option<String>,
        size: Option<i64>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClassifierDimension {
    pub id: DimensionId,
    pub workspace_id: WorkspaceId,
    pub key: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Classifier {
    pub id: ClassifierId,
    pub workspace_id: WorkspaceId,
    pub dimension_id: DimensionId,

    // 分类树父节点
    pub parent_id: Option<ClassifierId>,

    // 唯一于同一父节点下
    pub slug: String,
    pub name: String,
}
