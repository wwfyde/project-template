//! Immutable file identities shared by asset, document, and knowledge contexts.
//!
//! A file owns storage metadata, not a library membership. Replacing its bytes
//! creates a new file identity; business objects decide which identity to use.

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::shared::{AccountId, DomainError, DomainResult, require_non_blank};

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct FileId(pub Uuid);

/// A coarse content classification independent of business kind and file role.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MediaKind {
    Image,
    Document,
    Audio,
    Video,
    Archive,
    Data,
    Other,
}

impl MediaKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Image => "image",
            Self::Document => "document",
            Self::Audio => "audio",
            Self::Video => "video",
            Self::Archive => "archive",
            Self::Data => "data",
            Self::Other => "other",
        }
    }
}

/// Validated facts about a complete, immutable byte sequence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FileMetadata {
    filename: String,
    media_kind: MediaKind,
    mime_type: String,
    byte_size: u64,
    sha256: String,
}

impl FileMetadata {
    /// MIME is an essence (`type/subtype`), without parameters. SHA-256 is hex.
    /// Empty files are valid; the caller must verify the hash against the bytes.
    pub fn new(
        filename: impl Into<String>,
        media_kind: MediaKind,
        mime_type: impl Into<String>,
        byte_size: u64,
        sha256: impl Into<String>,
    ) -> DomainResult<Self> {
        let filename = filename.into();
        require_non_blank("filename", &filename)?;
        if filename.chars().any(char::is_control) {
            return Err(DomainError::InvalidValue {
                field: "filename",
                reason: "must not contain control characters",
            });
        }
        let mime_type = mime_type.into();
        if !valid_mime_type(&mime_type) {
            return Err(DomainError::InvalidValue {
                field: "mime_type",
                reason: "must be a MIME type/subtype without parameters",
            });
        }
        let sha256 = sha256.into();
        if sha256.len() != 64 || !sha256.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(DomainError::InvalidValue {
                field: "sha256",
                reason: "must contain exactly 64 hexadecimal characters",
            });
        }
        Ok(Self {
            filename,
            media_kind,
            mime_type: mime_type.to_ascii_lowercase(),
            byte_size,
            sha256: sha256.to_ascii_lowercase(),
        })
    }

    pub fn filename(&self) -> &str {
        &self.filename
    }

    pub const fn media_kind(&self) -> MediaKind {
        self.media_kind
    }

    pub fn mime_type(&self) -> &str {
        &self.mime_type
    }

    pub const fn byte_size(&self) -> u64 {
        self.byte_size
    }

    pub fn sha256(&self) -> &str {
        &self.sha256
    }
}

fn valid_mime_type(value: &str) -> bool {
    fn valid_token(token: &str) -> bool {
        !token.is_empty()
            && token.bytes().all(|byte| {
                byte.is_ascii_alphanumeric()
                    || matches!(
                        byte,
                        b'!' | b'#'
                            | b'$'
                            | b'%'
                            | b'&'
                            | b'\''
                            | b'+'
                            | b'-'
                            | b'.'
                            | b'^'
                            | b'_'
                            | b'`'
                            | b'|'
                            | b'~'
                    )
            })
    }
    value
        .split_once('/')
        .is_some_and(|(top_level, subtype)| valid_token(top_level) && valid_token(subtype))
}

/// An internal storage locator, never a public or expiring download URL.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StorageLocation {
    backend: String,
    bucket: String,
    key: String,
}

impl StorageLocation {
    pub fn new(
        backend: impl Into<String>,
        bucket: impl Into<String>,
        key: impl Into<String>,
    ) -> DomainResult<Self> {
        let backend = backend.into();
        let bucket = bucket.into();
        let key = key.into();
        require_non_blank("storage_backend", &backend)?;
        require_non_blank("storage_bucket", &bucket)?;
        require_non_blank("storage_key", &key)?;
        Ok(Self {
            backend,
            bucket,
            key,
        })
    }

    pub fn backend(&self) -> &str {
        &self.backend
    }

    pub fn bucket(&self) -> &str {
        &self.bucket
    }

    pub fn key(&self) -> &str {
        &self.key
    }
}

/// A completed file. Upload sessions and physical deletion are separate use cases.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct File {
    id: FileId,
    account_id: AccountId,
    metadata: FileMetadata,
    storage: StorageLocation,
    created_at: DateTime<Utc>,
}

impl File {
    pub fn new(
        id: FileId,
        account_id: AccountId,
        metadata: FileMetadata,
        storage: StorageLocation,
        created_at: DateTime<Utc>,
    ) -> Self {
        Self {
            id,
            account_id,
            metadata,
            storage,
            created_at,
        }
    }

    pub const fn id(&self) -> FileId {
        self.id
    }

    pub const fn account_id(&self) -> AccountId {
        self.account_id
    }

    pub fn metadata(&self) -> &FileMetadata {
        &self.metadata
    }

    pub fn storage(&self) -> &StorageLocation {
        &self.storage
    }

    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_canonicalizes_format_and_hash_without_rewriting_filename() {
        let metadata = FileMetadata::new(
            "品牌规范.pdf",
            MediaKind::Document,
            "Application/PDF",
            0,
            "A".repeat(64),
        )
        .unwrap();
        assert_eq!(metadata.filename(), "品牌规范.pdf");
        assert_eq!(metadata.mime_type(), "application/pdf");
        assert_eq!(metadata.sha256(), "a".repeat(64));
        assert_eq!(metadata.byte_size(), 0, "empty files are valid");
    }

    #[test]
    fn invalid_file_facts_are_rejected_before_a_file_can_be_constructed() {
        for (filename, mime_type, sha256, expected_field) in [
            (" ", "text/plain", "a".repeat(64), "filename"),
            ("bad\n.txt", "text/plain", "a".repeat(64), "filename"),
            ("note.txt", "plain", "a".repeat(64), "mime_type"),
            ("note.txt", "text/", "a".repeat(64), "mime_type"),
            (
                "note.txt",
                "text/plain; charset=utf-8",
                "a".repeat(64),
                "mime_type",
            ),
            ("note.txt", "text/plain", "a".repeat(63), "sha256"),
            ("note.txt", "text/plain", "z".repeat(64), "sha256"),
        ] {
            assert!(matches!(
                FileMetadata::new(filename, MediaKind::Document, mime_type, 1, sha256),
                Err(DomainError::InvalidValue { field, .. }) if field == expected_field
            ));
        }
        assert!(StorageLocation::new("s3", "files", " ").is_err());
    }
}
