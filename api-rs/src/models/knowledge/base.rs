use chrono::{DateTime, Utc};

use super::KnowledgeBaseId;
use crate::models::shared::{AccountId, DomainResult, require_non_blank};

#[derive(Clone, Debug, PartialEq)]
pub struct KnowledgeBase {
    id: KnowledgeBaseId,
    account_id: AccountId,
    name: String,
    created_at: DateTime<Utc>,
}

impl KnowledgeBase {
    pub fn new(
        id: KnowledgeBaseId,
        account_id: AccountId,
        name: impl Into<String>,
        created_at: DateTime<Utc>,
    ) -> DomainResult<Self> {
        let name = name.into();
        require_non_blank("name", &name)?;
        Ok(Self {
            id,
            account_id,
            name,
            created_at,
        })
    }

    pub fn rename(&mut self, name: impl Into<String>) -> DomainResult<()> {
        let name = name.into();
        require_non_blank("name", &name)?;
        self.name = name;
        Ok(())
    }

    pub fn id(&self) -> KnowledgeBaseId {
        self.id
    }
    pub fn account_id(&self) -> AccountId {
        self.account_id
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }
}
