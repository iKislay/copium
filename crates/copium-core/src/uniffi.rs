//! UniFFI bindings for Copium core library.
//!
//! Exposes core compression functionality to Python, Kotlin, Swift, Ruby via FFI.

use crate::tokenizer::count_tokens;
use crate::transforms::smart_crusher::SmartCrusher;

/// Compress a JSON string using Copium's SmartCrusher algorithm.
pub fn compress_json(input: &str, query_context: Option<&str>, max_items: u64) -> String {
    let config = crate::compression_policy::CompressionPolicy::default();
    let crusher = SmartCrusher::new(config);

    // Parse input as JSON value
    let json_value: serde_json::Value = match serde_json::from_str(input) {
        Ok(v) => v,
        Err(_) => return input.to_string(), // Return original if not valid JSON
    };

    // Compress
    match crusher.compress(&json_value, query_context, max_items as usize) {
        Ok(compressed) => compressed.to_string(),
        Err(_) => input.to_string(), // Return original on error
    }
}

/// Count tokens in a text string using tiktoken-compatible counting.
pub fn count_tokens(text: &str) -> u64 {
    count_tokens(text) as u64
}

/// Compress a tool output with relevance scoring.
pub fn compress_tool_output(
    content: &str,
    tool_name: &str,
    user_query: Option<&str>,
    max_tokens: u64,
) -> String {
    let config = crate::compression_policy::CompressionPolicy::default();
    let crusher = SmartCrusher::new(config);

    // Parse content as JSON
    let json_value: serde_json::Value = match serde_json::from_str(content) {
        Ok(v) => v,
        Err(_) => return content.to_string(),
    };

    // Compress with tool-specific settings
    match crusher.compress_tool_output(&json_value, tool_name, user_query, max_tokens as usize) {
        Ok(compressed) => compressed.to_string(),
        Err(_) => content.to_string(),
    }
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
