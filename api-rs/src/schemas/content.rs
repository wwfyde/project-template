//! Schema composition only: defining a representation does not create an endpoint.

use utoipa::OpenApi;

use super::asset::{AssetFileObject, AssetObject};
use super::document::{DocumentObject, DocumentRevisionObject};
use super::file::FileObject;
use super::knowledge::{
    KnowledgeBaseObject, KnowledgeBaseSourceObject, KnowledgeChunkObject, KnowledgeSourceObject,
    SourceCitationObject,
};

#[derive(OpenApi)]
#[openapi(components(schemas(
    FileObject,
    AssetObject,
    AssetFileObject,
    DocumentObject,
    DocumentRevisionObject,
    KnowledgeBaseObject,
    KnowledgeSourceObject,
    KnowledgeBaseSourceObject,
    KnowledgeChunkObject,
    SourceCitationObject,
)))]
pub struct ContentApi;

/// Register the same schema set in the application's existing OpenAPI document.
pub struct ContentSchemas;

impl utoipa::Modify for ContentSchemas {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        openapi.merge(ContentApi::openapi());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use serde_json::{Value, json};
    use uuid::Uuid;

    use crate::models::asset::{Asset, AssetFileRole, AssetId, AssetKind};
    use crate::models::document::{Document, DocumentId, DocumentKind, DocumentRevisionId};
    use crate::models::file::{File, FileId, FileMetadata, MediaKind, StorageLocation};
    use crate::models::knowledge::{
        KnowledgeChunk, KnowledgeChunkId, KnowledgeSource, KnowledgeSourceId, SourceLocator,
    };
    use crate::models::shared::AccountId;

    #[derive(OpenApi)]
    #[openapi(modifiers(&ContentSchemas))]
    struct RegisteredContentApi;

    #[derive(OpenApi)]
    #[openapi(nest((path = "/api", api = RegisteredContentApi)))]
    struct ApplicationApi;

    #[test]
    fn content_schemas_are_complete_without_advertising_unimplemented_endpoints() {
        let document = serde_json::to_value(ApplicationApi::openapi()).unwrap();
        let schemas = &document["components"]["schemas"];
        for name in [
            "FileObject",
            "MediaKind",
            "AssetObject",
            "AssetKind",
            "AssetFileObject",
            "AssetFileRole",
            "DocumentObject",
            "DocumentRevisionObject",
            "DocumentKind",
            "DocumentContent",
            "KnowledgeBaseObject",
            "KnowledgeSourceObject",
            "SourceOrigin",
            "KnowledgeBaseSourceObject",
            "IndexStatus",
            "KnowledgeChunkObject",
            "SourceLocator",
            "SourceCitationObject",
        ] {
            assert!(schemas.get(name).is_some(), "missing schema {name}");
        }
        assert!(document["paths"].as_object().unwrap().is_empty());
        assert_eq!(schemas["FileObject"]["properties"]["id"]["format"], "uuid");
        assert_eq!(
            schemas["SourceOrigin"]["oneOf"].as_array().unwrap().len(),
            2
        );
        assert_eq!(
            schemas["DocumentContent"]["oneOf"]
                .as_array()
                .unwrap()
                .len(),
            3
        );
        for field in ["storage", "storage_key", "bucket", "library_type"] {
            assert!(schemas["FileObject"]["properties"].get(field).is_none());
        }
        assert_local_references_resolve(&document, &document);
    }

    fn assert_local_references_resolve(value: &Value, document: &Value) {
        match value {
            Value::Object(object) => {
                if let Some(reference) = object.get("$ref").and_then(Value::as_str)
                    && let Some(pointer) = reference.strip_prefix('#')
                {
                    assert!(
                        document.pointer(pointer).is_some(),
                        "unresolved {reference}"
                    );
                }
                for child in object.values() {
                    assert_local_references_resolve(child, document);
                }
            }
            Value::Array(array) => {
                for child in array {
                    assert_local_references_resolve(child, document);
                }
            }
            _ => {}
        }
    }

    #[test]
    fn shared_pdf_keeps_business_roles_and_citations_separate_in_json() {
        let at = Utc::now();
        let account = AccountId(Uuid::now_v7());
        let file = File::new(
            FileId(Uuid::now_v7()),
            account,
            FileMetadata::new(
                "brand.pdf",
                MediaKind::Document,
                "application/pdf",
                120,
                "a".repeat(64),
            )
            .unwrap(),
            StorageLocation::new("s3", "private", "internal/brand.pdf").unwrap(),
            at,
        );
        let mut asset = Asset::new(
            AssetId(Uuid::now_v7()),
            account,
            "Brand",
            AssetKind::BrandGuideline,
            at,
        )
        .unwrap();
        asset.attach_file(&file, AssetFileRole::Original).unwrap();
        let mut document = Document::new(
            DocumentId(Uuid::now_v7()),
            account,
            "Brand guide",
            DocumentKind::Guide,
            at,
        )
        .unwrap();
        let revision = document
            .revise_markdown(
                DocumentRevisionId(Uuid::now_v7()),
                "Extracted brand guidance",
                Some(&file),
                at,
            )
            .unwrap();
        let source = KnowledgeSource::from_document_revision(
            KnowledgeSourceId(Uuid::now_v7()),
            account,
            &revision,
            at,
        )
        .unwrap();
        let chunk = KnowledgeChunk::new(
            KnowledgeChunkId(Uuid::now_v7()),
            &source,
            0,
            "Brand colors",
            SourceLocator::PdfPage { page: 12 },
            "parser-1/chunker-1/embedding-1",
        )
        .unwrap();
        document
            .revise_markdown(
                DocumentRevisionId(Uuid::now_v7()),
                "Updated guide",
                None,
                at,
            )
            .unwrap();

        let file_json = serde_json::to_value(FileObject::from(&file)).unwrap();
        let asset_json = serde_json::to_value(AssetObject::from(&asset)).unwrap();
        let revision_json = serde_json::to_value(DocumentRevisionObject::from(&revision)).unwrap();
        let citation_json = serde_json::to_value(SourceCitationObject::from(
            &chunk.citation(&source).unwrap(),
        ))
        .unwrap();
        assert_eq!(file_json["media_kind"], "document");
        assert!(file_json.get("storage").is_none());
        assert_eq!(asset_json["kind"], "brand_guideline");
        assert_eq!(asset_json["files"][0]["file_id"], json!(file.id().0));
        assert_eq!(asset_json["files"][0]["role"], "original");
        assert_eq!(revision_json["content"]["format"], "markdown");
        assert_eq!(
            citation_json["origin"]["revision_id"],
            json!(revision.id().0)
        );
        assert_eq!(citation_json["original_file_id"], json!(file.id().0));
        assert_eq!(
            citation_json["locator"],
            json!({"kind": "pdf_page", "page": 12})
        );
    }
}
