use chrono::{DateTime, Utc};

use super::KnowledgeSourceId;
use crate::models::document::{DocumentId, DocumentRevision, DocumentRevisionId};
use crate::models::file::{File, FileId};
use crate::models::shared::{AccountId, DomainResult, ensure_same_account, require_non_blank};

/// Exhaustive source alternatives prevent a snapshot referring to both a file
/// and an unrelated mutable document. Document references always pin a revision.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SourceOrigin {
    File {
        file_id: FileId,
    },
    DocumentRevision {
        document_id: DocumentId,
        revision_id: DocumentRevisionId,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct KnowledgeSource {
    id: KnowledgeSourceId,
    account_id: AccountId,
    title: String,
    origin: SourceOrigin,
    original_file_id: Option<FileId>,
    created_at: DateTime<Utc>,
}

impl KnowledgeSource {
    pub fn from_file(
        id: KnowledgeSourceId,
        account_id: AccountId,
        title: impl Into<String>,
        file: &File,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        ensure_same_account(account_id, file.account_id())?;
        let title = title.into();
        require_non_blank("title", &title)?;
        Ok(Self {
            id,
            account_id,
            title,
            origin: SourceOrigin::File { file_id: file.id() },
            original_file_id: Some(file.id()),
            created_at,
        })
    }

    pub fn from_document_revision(
        id: KnowledgeSourceId,
        account_id: AccountId,
        revision: &DocumentRevision,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        ensure_same_account(account_id, revision.account_id())?;
        Ok(Self {
            id,
            account_id,
            title: revision.title().to_owned(),
            origin: SourceOrigin::DocumentRevision {
                document_id: revision.document_id(),
                revision_id: revision.id(),
            },
            original_file_id: revision.source_file_id(),
            created_at,
        })
    }

    pub fn id(&self) -> KnowledgeSourceId {
        self.id
    }
    pub fn account_id(&self) -> AccountId {
        self.account_id
    }
    pub fn title(&self) -> &str {
        &self.title
    }
    pub fn origin(&self) -> &SourceOrigin {
        &self.origin
    }
    pub fn original_file_id(&self) -> Option<FileId> {
        self.original_file_id
    }
    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }
}
