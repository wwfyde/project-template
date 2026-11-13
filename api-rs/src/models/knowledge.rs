//! Knowledge sources, collection membership, and citations. Embeddings are a
//! rebuildable index; immutable source identities remain the evidence boundary.

mod base;
mod chunk;
mod index;
mod source;

#[cfg(test)]
mod tests;

pub use base::KnowledgeBase;
pub use chunk::{KnowledgeChunk, SourceCitation, SourceLocator};
pub use index::{IndexStatus, KnowledgeBaseSource};
pub use source::{KnowledgeSource, SourceOrigin};

use uuid::Uuid;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct KnowledgeBaseId(pub Uuid);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct KnowledgeSourceId(pub Uuid);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct KnowledgeChunkId(pub Uuid);

/// Distinguishes asynchronous attempts, including after removal and re-enrolment.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct IndexAttempt(pub Uuid);
