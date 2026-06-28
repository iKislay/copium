//! Session archive types and operations.
//!
//! Rust data structures for session archive management.
//! Used by the Python bindings for high-performance session operations.

use std::collections::HashMap;

/// A single message in a session archive.
#[derive(Debug, Clone)]
pub struct SessionMessage {
    /// Message type: human, assistant, tool_use, tool_result
    pub msg_type: String,
    /// Role: user, assistant, tool
    pub role: String,
    /// Message content
    pub content: String,
    /// Turn index in the conversation
    pub turn_index: usize,
    /// Content hash for dedup (SHA-256 prefix)
    pub content_hash: String,
    /// Metadata key-value pairs
    pub metadata: HashMap<String, String>,
}

/// Result of a compaction operation.
#[derive(Debug, Clone, Default)]
pub struct CompactResult {
    pub original_messages: usize,
    pub compacted_messages: usize,
    pub original_tokens_est: usize,
    pub compacted_tokens_est: usize,
    pub dedup_hits: usize,
    pub near_dedup_hits: usize,
    pub preamble_collapsed: usize,
    pub ansi_stripped: usize,
}

impl CompactResult {
    /// Percentage of tokens saved.
    pub fn savings_pct(&self) -> f64 {
        if self.original_tokens_est == 0 {
            return 0.0;
        }
        (self.original_tokens_est - self.compacted_tokens_est) as f64
            / self.original_tokens_est as f64
            * 100.0
    }
}

/// Supported agent session formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AgentFormat {
    ClaudeCode,
    Cursor,
    Aider,
    OpenCode,
    Unknown,
}

impl AgentFormat {
    /// Get the file extension for this format.
    pub fn extension(&self) -> &'static str {
        match self {
            AgentFormat::ClaudeCode => ".jsonl",
            AgentFormat::Cursor => ".json",
            AgentFormat::Aider => ".jsonl",
            AgentFormat::OpenCode => ".json",
            AgentFormat::Unknown => ".jsonl",
        }
    }

    /// Get the human-readable name.
    pub fn name(&self) -> &'static str {
        match self {
            AgentFormat::ClaudeCode => "claude_code",
            AgentFormat::Cursor => "cursor",
            AgentFormat::Aider => "aider",
            AgentFormat::OpenCode => "opencode",
            AgentFormat::Unknown => "unknown",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compact_result_savings() {
        let result = CompactResult {
            original_tokens_est: 1000,
            compacted_tokens_est: 300,
            ..Default::default()
        };
        assert!((result.savings_pct() - 70.0).abs() < 0.1);
    }

    #[test]
    fn test_compact_result_zero_division() {
        let result = CompactResult::default();
        assert_eq!(result.savings_pct(), 0.0);
    }

    #[test]
    fn test_agent_format() {
        assert_eq!(AgentFormat::ClaudeCode.extension(), ".jsonl");
        assert_eq!(AgentFormat::Cursor.name(), "cursor");
    }
}
