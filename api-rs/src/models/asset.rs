//! Reusable assets reference files with contextual roles; they never own bytes.

use chrono::{DateTime, Utc};
use uuid::Uuid;

use super::file::{File, FileId};
use super::shared::{AccountId, DomainError, DomainResult, ensure_same_account, require_non_blank};

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct AssetId(pub Uuid);

/// Business classification, independent of the format of any associated file.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AssetKind {
    Logo,
    Photo,
    Illustration,
    Template,
    BrandGuideline,
    Design,
    Other,
}

impl AssetKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Logo => "logo",
            Self::Photo => "photo",
            Self::Illustration => "illustration",
            Self::Template => "template",
            Self::BrandGuideline => "brand_guideline",
            Self::Design => "design",
            Self::Other => "other",
        }
    }
}

/// A file's role belongs to its association, not to the file itself.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AssetFileRole {
    Original,
    Preview,
    Thumbnail,
    Export,
    Mask,
    Reference,
}

impl AssetFileRole {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Original => "original",
            Self::Preview => "preview",
            Self::Thumbnail => "thumbnail",
            Self::Export => "export",
            Self::Mask => "mask",
            Self::Reference => "reference",
        }
    }
}

/// An association owned and changed by its asset aggregate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssetFile {
    file_id: FileId,
    role: AssetFileRole,
}

impl AssetFile {
    pub const fn file_id(&self) -> FileId {
        self.file_id
    }

    pub const fn role(&self) -> AssetFileRole {
        self.role
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Asset {
    id: AssetId,
    account_id: AccountId,
    title: String,
    kind: AssetKind,
    files: Vec<AssetFile>,
    created_at: DateTime<Utc>,
}

impl Asset {
    pub fn new(
        id: AssetId,
        account_id: AccountId,
        title: impl Into<String>,
        kind: AssetKind,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        let title = title.into();
        require_non_blank("asset_title", &title)?;
        Ok(Self {
            id,
            account_id,
            title,
            kind,
            files: Vec::new(),
            created_at,
        })
    }

    pub const fn id(&self) -> AssetId {
        self.id
    }

    pub const fn account_id(&self) -> AccountId {
        self.account_id
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub const fn kind(&self) -> AssetKind {
        self.kind
    }

    pub fn files(&self) -> &[AssetFile] {
        &self.files
    }

    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }

    pub fn rename(&mut self, title: impl Into<String>) -> DomainResult<()> {
        let title = title.into();
        require_non_blank("asset_title", &title)?;
        self.title = title;
        Ok(())
    }

    pub fn attach_file(&mut self, file: &File, role: AssetFileRole) -> DomainResult<()> {
        ensure_same_account(self.account_id, file.account_id())?;
        if self
            .files
            .iter()
            .any(|link| link.file_id == file.id() && link.role == role)
        {
            return Err(DomainError::DuplicateReference);
        }
        self.files.push(AssetFile {
            file_id: file.id(),
            role,
        });
        Ok(())
    }

    /// Detach only this role. The file and any other associations remain intact.
    pub fn detach_file(&mut self, file_id: FileId, role: AssetFileRole) -> DomainResult<AssetFile> {
        let position = self
            .files
            .iter()
            .position(|link| link.file_id == file_id && link.role == role)
            .ok_or(DomainError::ReferenceNotFound)?;
        Ok(self.files.remove(position))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::file::{FileMetadata, MediaKind, StorageLocation};

    fn file(account_id: AccountId) -> File {
        File::new(
            FileId(Uuid::now_v7()),
            account_id,
            FileMetadata::new(
                "brand.pdf",
                MediaKind::Document,
                "application/pdf",
                128,
                "a".repeat(64),
            )
            .unwrap(),
            StorageLocation::new("s3", "files", "brand.pdf").unwrap(),
            Utc::now(),
        )
    }

    fn asset(account_id: AccountId) -> Asset {
        Asset::new(
            AssetId(Uuid::now_v7()),
            account_id,
            "Brand guidelines",
            AssetKind::BrandGuideline,
            Utc::now(),
        )
        .unwrap()
    }

    #[test]
    fn a_file_can_have_multiple_roles_and_be_shared_by_assets() {
        let account_id = AccountId(Uuid::now_v7());
        let file = file(account_id);
        let original = file.clone();
        let mut first = asset(account_id);
        let mut second = asset(account_id);
        first.attach_file(&file, AssetFileRole::Original).unwrap();
        first.attach_file(&file, AssetFileRole::Preview).unwrap();
        second.attach_file(&file, AssetFileRole::Reference).unwrap();

        first
            .detach_file(file.id(), AssetFileRole::Original)
            .unwrap();

        assert_eq!(first.files().len(), 1);
        assert_eq!(first.files()[0].role(), AssetFileRole::Preview);
        assert_eq!(second.files()[0].file_id(), file.id());
        assert_eq!(file, original, "detaching never changes the stored file");
    }

    #[test]
    fn rejected_changes_leave_the_aggregate_unchanged() {
        let account_id = AccountId(Uuid::now_v7());
        let local_file = file(account_id);
        let foreign_file = file(AccountId(Uuid::now_v7()));
        let mut asset = asset(account_id);
        asset
            .attach_file(&local_file, AssetFileRole::Original)
            .unwrap();
        let original = asset.clone();

        assert_eq!(
            asset.attach_file(&foreign_file, AssetFileRole::Original),
            Err(DomainError::AccountMismatch)
        );
        assert_eq!(
            asset.attach_file(&local_file, AssetFileRole::Original),
            Err(DomainError::DuplicateReference)
        );
        assert_eq!(
            asset.detach_file(local_file.id(), AssetFileRole::Mask),
            Err(DomainError::ReferenceNotFound)
        );
        assert!(asset.rename(" ").is_err());
        assert_eq!(asset, original);
    }
}
