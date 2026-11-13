//! Public file representations. Internal storage locations stay in the domain.

use chrono::{DateTime, Utc};
use serde::Serialize;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::models::file as domain;

/// 文件内容大类；与资产分类、文档分类以及所属库相互独立。
#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum MediaKind {
    Image,
    Document,
    Audio,
    Video,
    Archive,
    Data,
    Other,
}

impl From<domain::MediaKind> for MediaKind {
    fn from(value: domain::MediaKind) -> Self {
        match value {
            domain::MediaKind::Image => Self::Image,
            domain::MediaKind::Document => Self::Document,
            domain::MediaKind::Audio => Self::Audio,
            domain::MediaKind::Video => Self::Video,
            domain::MediaKind::Archive => Self::Archive,
            domain::MediaKind::Data => Self::Data,
            domain::MediaKind::Other => Self::Other,
        }
    }
}

/// 完成上传的不可变文件。替换字节内容会产生新的文件 ID。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct FileObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub filename: String,
    pub media_kind: MediaKind,
    /// MIME essence，例如 application/pdf；不包含 charset 等参数。
    pub mime_type: String,
    pub byte_size: u64,
    #[schema(pattern = "^[a-f0-9]{64}$")]
    pub sha256: String,
    pub created_at: DateTime<Utc>,
}

impl From<&domain::File> for FileObject {
    fn from(file: &domain::File) -> Self {
        let metadata = file.metadata();
        Self {
            id: file.id().0,
            account_id: file.account_id().0,
            filename: metadata.filename().to_owned(),
            media_kind: metadata.media_kind().into(),
            mime_type: metadata.mime_type().to_owned(),
            byte_size: metadata.byte_size(),
            sha256: metadata.sha256().to_owned(),
            created_at: file.created_at(),
        }
    }
}
