use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::models::document as domain;

#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum DocumentKind {
    Note,
    Specification,
    Guide,
    Report,
    Other,
}

impl From<domain::DocumentKind> for DocumentKind {
    fn from(value: domain::DocumentKind) -> Self {
        match value {
            domain::DocumentKind::Note => Self::Note,
            domain::DocumentKind::Specification => Self::Specification,
            domain::DocumentKind::Guide => Self::Guide,
            domain::DocumentKind::Report => Self::Report,
            domain::DocumentKind::Other => Self::Other,
        }
    }
}

/// 文档的稳定身份；新建且尚无正文时，当前版本为空、版本号为零。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct DocumentObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub title: String,
    pub kind: DocumentKind,
    pub current_revision_id: Option<Uuid>,
    pub revision_no: u32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl From<&domain::Document> for DocumentObject {
    fn from(document: &domain::Document) -> Self {
        Self {
            id: document.id().0,
            account_id: document.account_id().0,
            title: document.title().to_owned(),
            kind: document.kind().into(),
            current_revision_id: document.current_revision_id().map(|id| id.0),
            revision_no: document.revision_no(),
            created_at: document.created_at(),
            updated_at: document.updated_at(),
        }
    }
}

/// 一个修订只有一种正文形式；原生 Markdown / 富文本无需先上传文件。
#[derive(Clone, Debug, Serialize, ToSchema)]
#[serde(tag = "format", rename_all = "snake_case")]
pub enum DocumentContent {
    Markdown {
        text: String,
    },
    RichText {
        #[schema(value_type = Object)]
        body: Value,
    },
    File {
        file_id: Uuid,
    },
}

impl From<&domain::DocumentContent> for DocumentContent {
    fn from(content: &domain::DocumentContent) -> Self {
        match content {
            domain::DocumentContent::Markdown { text } => Self::Markdown { text: text.clone() },
            domain::DocumentContent::RichText { body } => Self::RichText { body: body.clone() },
            domain::DocumentContent::File { file_id } => Self::File { file_id: file_id.0 },
        }
    }
}

/// 不可变的文档版本。知识来源引用此 ID，而非始终变化的当前版本。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct DocumentRevisionObject {
    pub id: Uuid,
    pub document_id: Uuid,
    pub account_id: Uuid,
    #[schema(minimum = 1)]
    pub revision_no: u32,
    /// 创建修订时的标题快照。
    pub title: String,
    pub content: DocumentContent,
    /// 导入、OCR 或文件正文的原件；原生正文可以为空。
    pub source_file_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
}

impl From<&domain::DocumentRevision> for DocumentRevisionObject {
    fn from(revision: &domain::DocumentRevision) -> Self {
        Self {
            id: revision.id().0,
            document_id: revision.document_id().0,
            account_id: revision.account_id().0,
            revision_no: revision.revision_no(),
            title: revision.title().to_owned(),
            content: revision.content().into(),
            source_file_id: revision.source_file_id().map(|id| id.0),
            created_at: revision.created_at(),
        }
    }
}
