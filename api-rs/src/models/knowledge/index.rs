use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::{
    IndexAttempt, KnowledgeBase, KnowledgeBaseId, KnowledgeChunk, KnowledgeSource,
    KnowledgeSourceId,
};
use crate::models::shared::{
    AccountId, DomainError, DomainResult, ensure_same_account, require_non_blank,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IndexStatus {
    Queued,
    Processing,
    Ready,
    Failed,
}

impl IndexStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Processing => "processing",
            Self::Ready => "ready",
            Self::Failed => "failed",
        }
    }
}

/// Membership has its own lifecycle. Its removal never mutates the source or
/// original file. Repositories must uniquely constrain (base ID, source ID).
#[derive(Clone, Debug, PartialEq)]
pub struct KnowledgeBaseSource {
    knowledge_base_id: KnowledgeBaseId,
    source_id: KnowledgeSourceId,
    account_id: AccountId,
    index_status: IndexStatus,
    index_version: Option<String>,
    active_attempt: Option<IndexAttempt>,
    last_error: Option<String>,
    enrolled_at: DateTime<Utc>,
    removed_at: Option<DateTime<Utc>>,
}

impl KnowledgeBaseSource {
    pub fn new(
        base: &KnowledgeBase,
        source: &KnowledgeSource,
        enrolled_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        ensure_same_account(base.account_id(), source.account_id())?;
        Ok(Self {
            knowledge_base_id: base.id(),
            source_id: source.id(),
            account_id: base.account_id(),
            index_status: IndexStatus::Queued,
            index_version: None,
            active_attempt: None,
            last_error: None,
            enrolled_at,
            removed_at: None,
        })
    }

    pub fn start_indexing(
        &mut self,
        index_version: impl Into<String>,
    ) -> DomainResult<IndexAttempt> {
        self.ensure_active()?;
        if !matches!(self.index_status, IndexStatus::Queued | IndexStatus::Failed) {
            return Err(DomainError::InvalidTransition);
        }
        let index_version = index_version.into();
        require_non_blank("index_version", &index_version)?;
        let attempt = IndexAttempt(Uuid::now_v7());
        self.index_status = IndexStatus::Processing;
        self.index_version = Some(index_version);
        self.active_attempt = Some(attempt);
        self.last_error = None;
        Ok(attempt)
    }

    pub fn mark_ready(&mut self, attempt: IndexAttempt) -> DomainResult<()> {
        self.ensure_current_attempt(attempt)?;
        self.index_status = IndexStatus::Ready;
        self.active_attempt = None;
        self.last_error = None;
        Ok(())
    }

    pub fn mark_failed(
        &mut self,
        attempt: IndexAttempt,
        error: impl Into<String>,
    ) -> DomainResult<()> {
        self.ensure_current_attempt(attempt)?;
        let error = error.into();
        require_non_blank("error", &error)?;
        self.index_status = IndexStatus::Failed;
        self.active_attempt = None;
        self.last_error = Some(error);
        Ok(())
    }

    /// Rebuilding invalidates any previous worker token before another attempt.
    pub fn queue_reindex(&mut self) -> DomainResult<()> {
        self.ensure_active()?;
        self.index_status = IndexStatus::Queued;
        self.index_version = None;
        self.active_attempt = None;
        self.last_error = None;
        Ok(())
    }

    pub fn remove(&mut self, at: DateTime<Utc>) -> DomainResult<()> {
        self.ensure_active()?;
        if at < self.enrolled_at {
            return Err(DomainError::InvalidValue {
                field: "removed_at",
                reason: "removal cannot predate enrolment",
            });
        }
        self.removed_at = Some(at);
        self.active_attempt = None;
        self.index_version = None;
        Ok(())
    }

    fn ensure_active(&self) -> DomainResult<()> {
        if self.removed_at.is_some() {
            return Err(DomainError::InvalidTransition);
        }
        Ok(())
    }

    fn ensure_current_attempt(&self, attempt: IndexAttempt) -> DomainResult<()> {
        self.ensure_active()?;
        if self.active_attempt != Some(attempt) {
            return Err(DomainError::RevisionMismatch);
        }
        if self.index_status != IndexStatus::Processing {
            return Err(DomainError::InvalidTransition);
        }
        Ok(())
    }

    pub fn knowledge_base_id(&self) -> KnowledgeBaseId {
        self.knowledge_base_id
    }
    pub fn source_id(&self) -> KnowledgeSourceId {
        self.source_id
    }
    pub fn account_id(&self) -> AccountId {
        self.account_id
    }
    pub fn index_status(&self) -> IndexStatus {
        self.index_status
    }
    pub fn index_version(&self) -> Option<&str> {
        self.index_version.as_deref()
    }
    pub fn active_attempt(&self) -> Option<IndexAttempt> {
        self.active_attempt
    }
    pub fn last_error(&self) -> Option<&str> {
        self.last_error.as_deref()
    }
    pub fn enrolled_at(&self) -> DateTime<Utc> {
        self.enrolled_at
    }
    pub fn removed_at(&self) -> Option<DateTime<Utc>> {
        self.removed_at
    }
    pub fn is_searchable(&self) -> bool {
        self.removed_at.is_none() && self.index_status == IndexStatus::Ready
    }

    /// Filters retained chunks against the version published in this base.
    /// Application services must additionally authorize the requesting actor.
    pub fn accepts_chunk(&self, chunk: &KnowledgeChunk) -> bool {
        self.is_searchable()
            && self.account_id == chunk.account_id()
            && self.source_id == chunk.source_id()
            && self.index_version.as_deref() == Some(chunk.index_version())
    }
}
