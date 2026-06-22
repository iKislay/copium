//! UniFFI bindings for Copium core library.
//!
//! Exposes core compression functionality to Python, Kotlin, Swift, Ruby via FFI.

use crate::tokenizer::get_tokenizer;
use crate::transforms::smart_crusher::{SmartCrusher, SmartCrusherConfig};

/// Compress a JSON string using Copium's SmartCrusher algorithm.
pub fn compress_json(input: &str, query_context: Option<&str>, _max_items: u64) -> String {
    let config = SmartCrusherConfig::default();
    let crusher = SmartCrusher::new(config);
    let query = query_context.unwrap_or("");
    crusher.crush(input, query, 0.5).compressed
}

/// Count tokens in a text string using tiktoken-compatible counting.
pub fn count_tokens(text: &str) -> u64 {
    get_tokenizer("gpt-4o").count_text(text) as u64
}

/// Compress a tool output with relevance scoring.
pub fn compress_tool_output(
    content: &str,
    tool_name: &str,
    user_query: Option<&str>,
    _max_tokens: u64,
) -> String {
    let config = SmartCrusherConfig::default();
    let crusher = SmartCrusher::new(config);
    let query = user_query.unwrap_or(tool_name);
    crusher.crush(content, query, 0.5).compressed
}

/// Compression statistics.
#[derive(Debug, Clone)]
pub struct CompressionStats {
    pub original_tokens: u64,
    pub compressed_tokens: u64,
    pub savings_ratio: f64,
    pub items_before: u64,
    pub items_after: u64,
}

/// Create a compression statistics object.
pub fn create_stats(
    original_tokens: u64,
    compressed_tokens: u64,
    items_before: u64,
    items_after: u64,
) -> CompressionStats {
    let savings_ratio = if original_tokens > 0 {
        1.0 - (compressed_tokens as f64 / original_tokens as f64)
    } else {
        0.0
    };

    CompressionStats {
        original_tokens,
        compressed_tokens,
        savings_ratio,
        items_before,
        items_after,
    }
}
