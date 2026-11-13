//! Authored documents and immutable revisions, independent of storage and HTTP.

use chrono::{DateTime, Utc};
use serde_json::Value;
use uuid::Uuid;

use super::file::{File, FileId};
use super::shared::{AccountId, DomainError, DomainResult, ensure_same_account, require_non_blank};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct DocumentId(pub Uuid);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct DocumentRevisionId(pub Uuid);

/// Business classification, separate from a file's media kind or MIME type.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DocumentKind {
    Note,
    Specification,
    Guide,
    Report,
    Other,
}

impl DocumentKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Note => "note",
            Self::Specification => "specification",
            Self::Guide => "guide",
            Self::Report => "report",
            Self::Other => "other",
        }
    }
}

/// A revision has one authoritative body. Creating a file-backed body requires
/// `Document::revise_file`, which checks the file's account before retaining its ID.
#[derive(Clone, Debug, PartialEq)]
pub enum DocumentContent {
    Markdown { text: String },
    RichText { body: Value },
    File { file_id: FileId },
}

/// Stable document identity. Repositories persist a new revision and its head
/// change atomically, with an expected revision number for concurrent writers.
#[derive(Clone, Debug, PartialEq)]
pub struct Document {
    id: DocumentId,
    account_id: AccountId,
    title: String,
    kind: DocumentKind,
    current_revision_id: Option<DocumentRevisionId>,
    revision_no: u32,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

impl Document {
    pub fn new(
        id: DocumentId,
        account_id: AccountId,
        title: impl Into<String>,
        kind: DocumentKind,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        let title = title.into();
        require_non_blank("title", &title)?;
        Ok(Self {
            id,
            account_id,
            title,
            kind,
            current_revision_id: None,
            revision_no: 0,
            created_at,
            updated_at: created_at,
        })
    }

    pub fn rename(&mut self, title: impl Into<String>, at: DateTime<Utc>) -> DomainResult<()> {
        let title = title.into();
        require_non_blank("title", &title)?;
        self.check_time(at)?;
        self.title = title;
        self.updated_at = at;
        Ok(())
    }

    pub fn revise_markdown(
        &mut self,
        id: DocumentRevisionId,
        text: impl Into<String>,
        source_file: Option<&File>,
        at: DateTime<Utc>,
    ) -> DomainResult<DocumentRevision> {
        let text = text.into();
        require_non_blank("text", &text)?;
        self.commit_revision(id, DocumentContent::Markdown { text }, source_file, at)
    }

    pub fn revise_rich_text(
        &mut self,
        id: DocumentRevisionId,
        body: Value,
        source_file: Option<&File>,
        at: DateTime<Utc>,
    ) -> DomainResult<DocumentRevision> {
        // The editor owns its node schema. The domain accepts a nonempty
        // structured object, never scalar JSON or an absent body.
        if !body.as_object().is_some_and(|object| !object.is_empty()) {
            return Err(DomainError::InvalidValue {
                field: "body",
                reason: "rich text must be a nonempty JSON object",
            });
        }
        self.commit_revision(id, DocumentContent::RichText { body }, source_file, at)
    }

    pub fn revise_file(
        &mut self,
        id: DocumentRevisionId,
        file: &File,
        at: DateTime<Utc>,
    ) -> DomainResult<DocumentRevision> {
        self.commit_revision(
            id,
            DocumentContent::File { file_id: file.id() },
            Some(file),
            at,
        )
    }

    fn commit_revision(
        &mut self,
        id: DocumentRevisionId,
        content: DocumentContent,
        source_file: Option<&File>,
        at: DateTime<Utc>,
    ) -> DomainResult<DocumentRevision> {
        self.check_time(at)?;
        if self.current_revision_id == Some(id) {
            return Err(DomainError::DuplicateReference);
        }
        if let Some(file) = source_file {
            ensure_same_account(self.account_id, file.account_id())?;
        }
        let revision_no = self
            .revision_no
            .checked_add(1)
            .ok_or(DomainError::InvalidValue {
                field: "revision_no",
                reason: "revision number overflow",
            })?;
        let revision = DocumentRevision {
            id,
            document_id: self.id,
            account_id: self.account_id,
            revision_no,
            title: self.title.clone(),
            content,
            source_file_id: source_file.map(File::id),
            created_at: at,
        };
        self.current_revision_id = Some(id);
        self.revision_no = revision_no;
        self.updated_at = at;
        Ok(revision)
    }

    fn check_time(&self, at: DateTime<Utc>) -> DomainResult<()> {
        if at < self.updated_at {
            return Err(DomainError::InvalidValue {
                field: "created_at",
                reason: "document changes cannot predate the current head",
            });
        }
        Ok(())
    }

    pub fn id(&self) -> DocumentId {
        self.id
    }

    pub fn account_id(&self) -> AccountId {
        self.account_id
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn kind(&self) -> DocumentKind {
        self.kind
    }

    pub fn current_revision_id(&self) -> Option<DocumentRevisionId> {
        self.current_revision_id
    }

    pub fn revision_no(&self) -> u32 {
        self.revision_no
    }

    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }

    pub fn updated_at(&self) -> DateTime<Utc> {
        self.updated_at
    }
}

/// Content and source provenance are frozen together. A revision has no setters
/// and cannot be deserialized around the document's validation methods.
#[derive(Clone, Debug, PartialEq)]
pub struct DocumentRevision {
    id: DocumentRevisionId,
    document_id: DocumentId,
    account_id: AccountId,
    revision_no: u32,
    title: String,
    content: DocumentContent,
    source_file_id: Option<FileId>,
    created_at: DateTime<Utc>,
}

impl DocumentRevision {
    pub fn id(&self) -> DocumentRevisionId {
        self.id
    }

    pub fn document_id(&self) -> DocumentId {
        self.document_id
    }

    pub fn account_id(&self) -> AccountId {
        self.account_id
    }

    pub fn revision_no(&self) -> u32 {
        self.revision_no
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn content(&self) -> &DocumentContent {
        &self.content
    }

    pub fn source_file_id(&self) -> Option<FileId> {
        self.source_file_id
    }

    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::file::{FileMetadata, MediaKind, StorageLocation};

    fn file(account_id: AccountId, at: DateTime<Utc>) -> File {
        File::new(
            FileId(Uuid::now_v7()),
            account_id,
            FileMetadata::new(
                "guide.pdf",
                MediaKind::Document,
                "application/pdf",
                10,
                "a".repeat(64),
            )
            .unwrap(),
            StorageLocation::new("object", "library", "guide.pdf").unwrap(),
            at,
        )
    }

    #[test]
    fn revisions_preserve_content_title_and_original_file() {
        let at = Utc::now();
        let account = AccountId(Uuid::now_v7());
        let original = file(account, at);
        let mut document = Document::new(
            DocumentId(Uuid::now_v7()),
            account,
            "Guide",
            DocumentKind::Guide,
            at,
        )
        .unwrap();
        let first = document
            .revise_markdown(
                DocumentRevisionId(Uuid::now_v7()),
                "First version",
                Some(&original),
                at,
            )
            .unwrap();
        document.rename("Updated guide", at).unwrap();
        let second = document
            .revise_markdown(
                DocumentRevisionId(Uuid::now_v7()),
                "Second version",
                None,
                at,
            )
            .unwrap();

        assert_eq!(first.revision_no(), 1);
        assert_eq!(first.title(), "Guide");
        assert_eq!(first.source_file_id(), Some(original.id()));
        assert_eq!(
            first.content(),
            &DocumentContent::Markdown {
                text: "First version".into()
            }
        );
        assert_eq!(second.revision_no(), 2);
        assert_eq!(second.source_file_id(), None);
        assert_eq!(document.current_revision_id(), Some(second.id()));
    }

    #[test]
    fn rejected_revisions_do_not_advance_the_document() {
        let at = Utc::now();
        let mut document = Document::new(
            DocumentId(Uuid::now_v7()),
            AccountId(Uuid::now_v7()),
            "Guide",
            DocumentKind::Guide,
            at,
        )
        .unwrap();
        let unchanged = document.clone();
        let foreign_file = file(AccountId(Uuid::now_v7()), at);
        assert_eq!(
            document.revise_file(DocumentRevisionId(Uuid::now_v7()), &foreign_file, at),
            Err(DomainError::AccountMismatch),
        );
        assert!(
            document
                .revise_markdown(DocumentRevisionId(Uuid::now_v7()), "  ", None, at)
                .is_err()
        );
        assert!(
            document
                .revise_rich_text(DocumentRevisionId(Uuid::now_v7()), Value::Null, None, at)
                .is_err()
        );
        assert_eq!(document, unchanged);
    }

    #[test]
    fn file_backed_revision_and_native_rich_text_have_distinct_bodies() {
        let at = Utc::now();
        let account = AccountId(Uuid::now_v7());
        let original = file(account, at);
        let mut document = Document::new(
            DocumentId(Uuid::now_v7()),
            account,
            "Guide",
            DocumentKind::Guide,
            at,
        )
        .unwrap();
        let imported = document
            .revise_file(DocumentRevisionId(Uuid::now_v7()), &original, at)
            .unwrap();
        assert_eq!(
            imported.content(),
            &DocumentContent::File {
                file_id: original.id()
            }
        );
        let body = serde_json::json!({"type": "doc", "content": []});
        let authored = document
            .revise_rich_text(DocumentRevisionId(Uuid::now_v7()), body.clone(), None, at)
            .unwrap();
        assert_eq!(authored.content(), &DocumentContent::RichText { body });
        assert_eq!(authored.source_file_id(), None);
    }
}
