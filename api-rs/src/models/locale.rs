use serde::{Deserialize, Serialize};
use std::{fmt, str::FromStr};
use utoipa::ToSchema;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize, ToSchema)]
pub enum Locale {
    #[default]
    #[serde(rename = "zh-CN")]
    ZhCn,
    #[serde(rename = "en-US")]
    EnUs,
    #[serde(rename = "ja-JP")]
    JaJp,
}

impl Locale {
    pub const fn as_str(self) -> &'static str {
        match self {
            Locale::EnUs => "en-US",
            Locale::ZhCn => "zh-CN",
            Locale::JaJp => "ja-JP",
        }
    }
}

impl fmt::Display for Locale {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, thiserror::Error)]
#[error("unsupported locale: {0}")]
pub struct ParseLocaleError(String);

impl FromStr for Locale {
    type Err = ParseLocaleError;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "en-US" => Ok(Locale::EnUs),
            "zh-CN" => Ok(Locale::ZhCn),
            "ja-JP" => Ok(Locale::JaJp),
            other => Err(ParseLocaleError(other.to_owned())),
        }
    }
}
