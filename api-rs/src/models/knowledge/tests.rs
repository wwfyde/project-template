use super::*;
use crate::models::document::{Document, DocumentId, DocumentKind, DocumentRevisionId};
use crate::models::file::{File, FileId};
use crate::models::file::{FileMetadata, MediaKind, StorageLocation};
use crate::models::shared::{AccountId, DomainError};
use chrono::{DateTime, Utc};

fn source(account: AccountId, at: DateTime<Utc>) -> KnowledgeSource {
    let file = File::new(
        FileId(Uuid::now_v7()),
        account,
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
    );
    KnowledgeSource::from_file(
        KnowledgeSourceId(Uuid::now_v7()),
        account,
        "Guide",
        &file,
        at,
    )
    .unwrap()
}

#[test]
fn citation_retains_revision_and_original_after_document_changes() {
    let at = Utc::now();
    let account = AccountId(Uuid::now_v7());
    let mut document = Document::new(
        DocumentId(Uuid::now_v7()),
        account,
        "Original guide",
        DocumentKind::Guide,
        at,
    )
    .unwrap();
    let first = document
        .revise_markdown(
            DocumentRevisionId(Uuid::now_v7()),
            "First version",
            None,
            at,
        )
        .unwrap();
    let snapshot = KnowledgeSource::from_document_revision(
        KnowledgeSourceId(Uuid::now_v7()),
        account,
        &first,
        at,
    )
    .unwrap();
    let chunk = KnowledgeChunk::new(
        KnowledgeChunkId(Uuid::now_v7()),
        &snapshot,
        0,
        "First version",
        SourceLocator::TextRange { start: 0, end: 13 },
        "parser-1/chunker-1/embedding-1",
    )
    .unwrap();
    document.rename("New guide", at).unwrap();
    let second = document
        .revise_markdown(
            DocumentRevisionId(Uuid::now_v7()),
            "Second version",
            None,
            at,
        )
        .unwrap();
    let citation = chunk.citation(&snapshot).unwrap();
    assert_eq!(citation.title(), "Original guide");
    assert_eq!(
        citation.origin(),
        &SourceOrigin::DocumentRevision {
            document_id: document.id(),
            revision_id: first.id()
        }
    );
    assert_ne!(document.current_revision_id(), Some(first.id()));
    assert_eq!(document.current_revision_id(), Some(second.id()));
    assert_eq!(citation.original_file_id(), None);
    assert_eq!(
        chunk.citation(&source(account, at)),
        Err(DomainError::RevisionMismatch)
    );
}

#[test]
fn one_source_can_join_two_bases_without_sharing_index_state() {
    let at = Utc::now();
    let account = AccountId(Uuid::now_v7());
    let snapshot = source(account, at);
    let first = KnowledgeBase::new(KnowledgeBaseId(Uuid::now_v7()), account, "Brand", at).unwrap();
    let second =
        KnowledgeBase::new(KnowledgeBaseId(Uuid::now_v7()), account, "Support", at).unwrap();
    let mut a = KnowledgeBaseSource::new(&first, &snapshot, at).unwrap();
    let b = KnowledgeBaseSource::new(&second, &snapshot, at).unwrap();
    let attempt = a.start_indexing("v1").unwrap();
    a.mark_ready(attempt).unwrap();
    assert!(a.is_searchable());
    assert!(!b.is_searchable());
    a.remove(at).unwrap();
    assert!(!a.is_searchable());
    assert_eq!(b.source_id(), snapshot.id());
    assert!(snapshot.original_file_id().is_some());
}

#[test]
fn stale_or_removed_index_workers_cannot_publish_results() {
    let at = Utc::now();
    let account = AccountId(Uuid::now_v7());
    let base = KnowledgeBase::new(KnowledgeBaseId(Uuid::now_v7()), account, "Brand", at).unwrap();
    let mut membership = KnowledgeBaseSource::new(&base, &source(account, at), at).unwrap();
    let stale = membership.start_indexing("v1").unwrap();
    membership.queue_reindex().unwrap();
    let current = membership.start_indexing("v1").unwrap();
    let unchanged = membership.clone();
    assert_eq!(
        membership.mark_ready(stale),
        Err(DomainError::RevisionMismatch)
    );
    assert_eq!(membership, unchanged);
    membership
        .mark_failed(current, "index unavailable")
        .unwrap();
    let retry = membership.start_indexing("v1").unwrap();
    assert_eq!(membership.last_error(), None);
    membership.remove(at).unwrap();
    assert_eq!(
        membership.mark_ready(retry),
        Err(DomainError::InvalidTransition)
    );
    assert_eq!(
        membership.queue_reindex(),
        Err(DomainError::InvalidTransition)
    );
    assert!(!membership.is_searchable());
}

#[test]
fn published_index_version_excludes_retained_old_chunks() {
    let at = Utc::now();
    let account = AccountId(Uuid::now_v7());
    let base = KnowledgeBase::new(KnowledgeBaseId(Uuid::now_v7()), account, "Brand", at).unwrap();
    let snapshot = source(account, at);
    let mut membership = KnowledgeBaseSource::new(&base, &snapshot, at).unwrap();
    let old = KnowledgeChunk::new(
        KnowledgeChunkId(Uuid::now_v7()),
        &snapshot,
        0,
        "Old extraction",
        SourceLocator::WholeSource,
        "v1",
    )
    .unwrap();
    let current = KnowledgeChunk::new(
        KnowledgeChunkId(Uuid::now_v7()),
        &snapshot,
        0,
        "New extraction",
        SourceLocator::WholeSource,
        "v2",
    )
    .unwrap();
    let first = membership.start_indexing("v1").unwrap();
    membership.mark_ready(first).unwrap();
    assert!(membership.accepts_chunk(&old));
    assert!(!membership.accepts_chunk(&current));
    membership.queue_reindex().unwrap();
    assert!(!membership.accepts_chunk(&old));
    let unchanged = membership.clone();
    assert!(membership.start_indexing(" ").is_err());
    assert_eq!(membership, unchanged);
    let second = membership.start_indexing("v2").unwrap();
    membership.mark_ready(second).unwrap();
    assert!(!membership.accepts_chunk(&old));
    assert!(membership.accepts_chunk(&current));
    membership.remove(at).unwrap();
    assert!(!membership.accepts_chunk(&current));
}

#[test]
fn cross_account_sources_and_enrolment_are_rejected() {
    let at = Utc::now();
    let account = AccountId(Uuid::now_v7());
    let foreign = AccountId(Uuid::now_v7());
    let base = KnowledgeBase::new(KnowledgeBaseId(Uuid::now_v7()), account, "Brand", at).unwrap();
    assert_eq!(
        KnowledgeBaseSource::new(&base, &source(foreign, at), at),
        Err(DomainError::AccountMismatch)
    );
    let mut document = Document::new(
        DocumentId(Uuid::now_v7()),
        foreign,
        "Guide",
        DocumentKind::Guide,
        at,
    )
    .unwrap();
    let revision = document
        .revise_markdown(DocumentRevisionId(Uuid::now_v7()), "Text", None, at)
        .unwrap();
    assert_eq!(
        KnowledgeSource::from_document_revision(
            KnowledgeSourceId(Uuid::now_v7()),
            account,
            &revision,
            at
        ),
        Err(DomainError::AccountMismatch)
    );
}

#[test]
fn chunk_locations_reject_empty_ranges_and_nonfinite_coordinates() {
    let snapshot = source(AccountId(Uuid::now_v7()), Utc::now());
    for locator in [
        SourceLocator::PdfPage { page: 0 },
        SourceLocator::TextRange { start: 5, end: 5 },
        SourceLocator::TimeRange {
            start_ms: 20,
            end_ms: 10,
        },
        SourceLocator::DocumentBlock {
            block_id: " ".into(),
        },
        SourceLocator::ImageRegion {
            x: f64::NAN,
            y: 0.0,
            width: 0.5,
            height: 0.5,
        },
        SourceLocator::ImageRegion {
            x: 0.9,
            y: 0.0,
            width: 0.5,
            height: 0.5,
        },
    ] {
        assert!(
            KnowledgeChunk::new(
                KnowledgeChunkId(Uuid::now_v7()),
                &snapshot,
                0,
                "Text",
                locator,
                "v1"
            )
            .is_err()
        );
    }
    for locator in [
        SourceLocator::WholeSource,
        SourceLocator::PdfPage { page: 1 },
        SourceLocator::TextRange { start: 0, end: 5 },
        SourceLocator::TimeRange {
            start_ms: 0,
            end_ms: 10,
        },
        SourceLocator::DocumentBlock {
            block_id: "paragraph-1".into(),
        },
        SourceLocator::ImageRegion {
            x: 0.0,
            y: 0.0,
            width: 1.0,
            height: 1.0,
        },
    ] {
        KnowledgeChunk::new(
            KnowledgeChunkId(Uuid::now_v7()),
            &snapshot,
            0,
            "Text",
            locator,
            "v1",
        )
        .unwrap();
    }
}
