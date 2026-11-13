use chrono::{DateTime, Utc};
use serde::Serialize;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::models::asset as domain;

/// 资产的业务分类，与关联文件的 MIME 和内容大类无关。
#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum AssetKind {
    Logo,
    Photo,
    Illustration,
    Template,
    BrandGuideline,
    Design,
    Other,
}

impl From<domain::AssetKind> for AssetKind {
    fn from(value: domain::AssetKind) -> Self {
        match value {
            domain::AssetKind::Logo => Self::Logo,
            domain::AssetKind::Photo => Self::Photo,
            domain::AssetKind::Illustration => Self::Illustration,
            domain::AssetKind::Template => Self::Template,
            domain::AssetKind::BrandGuideline => Self::BrandGuideline,
            domain::AssetKind::Design => Self::Design,
            domain::AssetKind::Other => Self::Other,
        }
    }
}

/// 文件在当前资产中的作用；同一文件可以承担不同作用。
#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum AssetFileRole {
    Original,
    Preview,
    Thumbnail,
    Export,
    Mask,
    Reference,
}

impl From<domain::AssetFileRole> for AssetFileRole {
    fn from(value: domain::AssetFileRole) -> Self {
        match value {
            domain::AssetFileRole::Original => Self::Original,
            domain::AssetFileRole::Preview => Self::Preview,
            domain::AssetFileRole::Thumbnail => Self::Thumbnail,
            domain::AssetFileRole::Export => Self::Export,
            domain::AssetFileRole::Mask => Self::Mask,
            domain::AssetFileRole::Reference => Self::Reference,
        }
    }
}

/// 解除此关联不会删除原文件。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct AssetFileObject {
    pub file_id: Uuid,
    pub role: AssetFileRole,
}

impl From<&domain::AssetFile> for AssetFileObject {
    fn from(link: &domain::AssetFile) -> Self {
        Self {
            file_id: link.file_id().0,
            role: link.role().into(),
        }
    }
}

/// 可复用资产的稳定身份，持有文件引用而非文件字节。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct AssetObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub title: String,
    pub kind: AssetKind,
    pub files: Vec<AssetFileObject>,
    pub created_at: DateTime<Utc>,
}

impl From<&domain::Asset> for AssetObject {
    fn from(asset: &domain::Asset) -> Self {
        Self {
            id: asset.id().0,
            account_id: asset.account_id().0,
            title: asset.title().to_owned(),
            kind: asset.kind().into(),
            files: asset.files().iter().map(Into::into).collect(),
            created_at: asset.created_at(),
        }
    }
}
