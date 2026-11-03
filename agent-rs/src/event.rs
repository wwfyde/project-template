use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum TriggerEvent {
    /// 定时
    #[serde(alias = "定时")]
    Scheduled,
    /// 告警
    Alert,
    /// 报错
    Error,
    /// 意见
    Feedback,
    /// 新来源
    NewSource,
    /// 决定
    Decision,
}
