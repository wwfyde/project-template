//! Knowledge representations preserve versioned provenance, independently of
//! the vector-store provider. They do not expose embeddings or storage keys.

use chrono::{DateTime, Utc};
use serde::Serialize;
use utoipa::ToSchema;
use uuid::Uuid;

use crate::models::knowledge as domain;

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct KnowledgeBaseObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub name: String,
    pub created_at: DateTime<Utc>,
}

impl From<&domain::KnowledgeBase> for KnowledgeBaseObject {
    fn from(base: &domain::KnowledgeBase) -> Self {
        Self {
            id: base.id().0,
            account_id: base.account_id().0,
            name: base.name().to_owned(),
            created_at: base.created_at(),
        }
    }
}

/// 来源必须指向一个固定文件或文档修订；两种来源互斥。
#[derive(Clone, Debug, Serialize, ToSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SourceOrigin {
    File {
        file_id: Uuid,
    },
    DocumentRevision {
        document_id: Uuid,
        revision_id: Uuid,
    },
}

impl From<&domain::SourceOrigin> for SourceOrigin {
    fn from(origin: &domain::SourceOrigin) -> Self {
        match origin {
            domain::SourceOrigin::File { file_id } => Self::File { file_id: file_id.0 },
            domain::SourceOrigin::DocumentRevision {
                document_id,
                revision_id,
            } => Self::DocumentRevision {
                document_id: document_id.0,
                revision_id: revision_id.0,
            },
        }
    }
}

/// 不可变来源快照，可由多个知识库收录。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct KnowledgeSourceObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub title: String,
    pub origin: SourceOrigin,
    /// 原始文件的本地 ID。原生文档来源可以为空。
    pub original_file_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
}

impl From<&domain::KnowledgeSource> for KnowledgeSourceObject {
    fn from(source: &domain::KnowledgeSource) -> Self {
        Self {
            id: source.id().0,
            account_id: source.account_id().0,
            title: source.title().to_owned(),
            origin: source.origin().into(),
            original_file_id: source.original_file_id().map(|id| id.0),
            created_at: source.created_at(),
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum IndexStatus {
    Queued,
    Processing,
    Ready,
    Failed,
}

impl From<domain::IndexStatus> for IndexStatus {
    fn from(value: domain::IndexStatus) -> Self {
        match value {
            domain::IndexStatus::Queued => Self::Queued,
            domain::IndexStatus::Processing => Self::Processing,
            domain::IndexStatus::Ready => Self::Ready,
            domain::IndexStatus::Failed => Self::Failed,
        }
    }
}

/// 知识库与来源的收录关系。索引状态属于此关联，不属于原文件。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct KnowledgeBaseSourceObject {
    pub knowledge_base_id: Uuid,
    pub source_id: Uuid,
    pub account_id: Uuid,
    pub index_status: IndexStatus,
    /// 当前处理或已就绪的索引配置版本；排队及移除后为空。
    pub index_version: Option<String>,
    pub enrolled_at: DateTime<Utc>,
    pub removed_at: Option<DateTime<Utc>>,
    /// 仅代表当前关联索引就绪且未移除，调用方仍必须执行权限检查。
    pub is_searchable: bool,
}

impl From<&domain::KnowledgeBaseSource> for KnowledgeBaseSourceObject {
    fn from(link: &domain::KnowledgeBaseSource) -> Self {
        Self {
            knowledge_base_id: link.knowledge_base_id().0,
            source_id: link.source_id().0,
            account_id: link.account_id().0,
            index_status: link.index_status().into(),
            index_version: link.index_version().map(str::to_owned),
            enrolled_at: link.enrolled_at(),
            removed_at: link.removed_at(),
            is_searchable: link.is_searchable(),
        }
    }
}

/// 原始来源中的位置。文本区间采用 Unicode 字符索引、左闭右开；
/// 图像区域坐标归一化至 [0, 1]；音视频位置以毫秒计。
#[derive(Clone, Debug, Serialize, ToSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SourceLocator {
    WholeSource,
    PdfPage {
        #[schema(minimum = 1)]
        page: u32,
    },
    TextRange {
        start: u64,
        end: u64,
    },
    DocumentBlock {
        block_id: String,
    },
    ImageRegion {
        #[schema(minimum = 0, maximum = 1)]
        x: f64,
        #[schema(minimum = 0, maximum = 1)]
        y: f64,
        #[schema(exclusive_minimum = 0, maximum = 1)]
        width: f64,
        #[schema(exclusive_minimum = 0, maximum = 1)]
        height: f64,
    },
    TimeRange {
        start_ms: u64,
        end_ms: u64,
    },
}

impl From<&domain::SourceLocator> for SourceLocator {
    fn from(locator: &domain::SourceLocator) -> Self {
        match locator {
            domain::SourceLocator::WholeSource => Self::WholeSource,
            domain::SourceLocator::PdfPage { page } => Self::PdfPage { page: *page },
            domain::SourceLocator::TextRange { start, end } => Self::TextRange {
                start: *start,
                end: *end,
            },
            domain::SourceLocator::DocumentBlock { block_id } => Self::DocumentBlock {
                block_id: block_id.clone(),
            },
            domain::SourceLocator::ImageRegion {
                x,
                y,
                width,
                height,
            } => Self::ImageRegion {
                x: *x,
                y: *y,
                width: *width,
                height: *height,
            },
            domain::SourceLocator::TimeRange { start_ms, end_ms } => Self::TimeRange {
                start_ms: *start_ms,
                end_ms: *end_ms,
            },
        }
    }
}

/// 可检索片段及其来源位置。向量由索引适配器管理。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct KnowledgeChunkObject {
    pub id: Uuid,
    pub account_id: Uuid,
    pub source_id: Uuid,
    /// 同一来源和索引版本内从零开始的片段序号。
    pub ordinal: u32,
    pub text: String,
    pub locator: SourceLocator,
    /// 标识解析、分块和嵌入配置的版本。
    pub index_version: String,
}

impl From<&domain::KnowledgeChunk> for KnowledgeChunkObject {
    fn from(chunk: &domain::KnowledgeChunk) -> Self {
        Self {
            id: chunk.id().0,
            account_id: chunk.account_id().0,
            source_id: chunk.source_id().0,
            ordinal: chunk.ordinal(),
            text: chunk.text().to_owned(),
            locator: chunk.locator().into(),
            index_version: chunk.index_version().to_owned(),
        }
    }
}

/// 已核对来源身份的引用。原文件链接由交付层鉴权后生成。
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct SourceCitationObject {
    pub chunk_id: Uuid,
    pub source_id: Uuid,
    pub title: String,
    pub origin: SourceOrigin,
    pub original_file_id: Option<Uuid>,
    pub locator: SourceLocator,
}

impl From<&domain::SourceCitation> for SourceCitationObject {
    fn from(citation: &domain::SourceCitation) -> Self {
        Self {
            chunk_id: citation.chunk_id().0,
            source_id: citation.source_id().0,
            title: citation.title().to_owned(),
            origin: citation.origin().into(),
            original_file_id: citation.original_file_id().map(|id| id.0),
            locator: citation.locator().into(),
        }
    }
}
