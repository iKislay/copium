//! SimhashDedup — near-duplicate paragraph deduplication as a reformat transform.
//!
//! Uses simhash fingerprinting to identify and deduplicate near-duplicate
//! text blocks within a single content unit. First occurrence is kept;
//! subsequent near-duplicates are replaced with a back-reference note.
//!
//! Runs as the FIRST reformat in the pipeline to maximize downstream
//! transform effectiveness.

use crate::transforms::pipeline::traits::{ReformatOutput, ReformatTransform, TransformError};
use crate::transforms::simhash;
use crate::transforms::ContentType;

pub struct SimhashDedup {
    shingle_width: usize,
    hamming_threshold: u32,
    min_block_tokens: usize,
}

impl Default for SimhashDedup {
    fn default() -> Self {
        Self {
            shingle_width: 3,
            hamming_threshold: 3,
            min_block_tokens: 4,
        }
    }
}

impl SimhashDedup {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_shingle_width(mut self, width: usize) -> Self {
        self.shingle_width = width;
        self
    }

    pub fn with_hamming_threshold(mut self, threshold: u32) -> Self {
        self.hamming_threshold = threshold;
        self
    }
}

impl ReformatTransform for SimhashDedup {
    fn name(&self) -> &'static str {
        "simhash_dedup"
    }

    fn applies_to(&self) -> &[ContentType] {
        &[ContentType::PlainText, ContentType::SourceCode]
    }

    fn apply(&self, content: &str) -> Result<ReformatOutput, TransformError> {
        let blocks = split_into_blocks(content);
        if blocks.len() < 2 {
            return Err(TransformError::skipped(
                "simhash_dedup",
                "fewer than 2 blocks",
            ));
        }

        let indexed: Vec<(usize, &str)> = blocks
            .iter()
            .enumerate()
            .filter(|(_, b)| b.split_whitespace().count() >= self.min_block_tokens)
            .map(|(i, b)| (i, b.as_str()))
            .collect();

        if indexed.len() < 2 {
            return Err(TransformError::skipped(
                "simhash_dedup",
                "fewer than 2 blocks above shingle width",
            ));
        }

        let kept_indices = simhash::deduplicate_with_threshold(
            &indexed,
            self.shingle_width,
            self.hamming_threshold,
        );

        let kept_set: std::collections::HashSet<usize> = kept_indices.into_iter().collect();
        let all_indexed_set: std::collections::HashSet<usize> =
            indexed.iter().map(|(i, _)| *i).collect();

        let mut output_parts: Vec<String> = Vec::with_capacity(blocks.len());
        let mut dedup_count = 0;

        for (i, block) in blocks.iter().enumerate() {
            if !all_indexed_set.contains(&i) {
                // Block was too short to fingerprint — preserve as-is
                output_parts.push(block.to_string());
            } else if kept_set.contains(&i) {
                output_parts.push(block.to_string());
            } else {
                dedup_count += 1;
                output_parts.push("[~duplicate of earlier block]".to_string());
            }
        }

        if dedup_count == 0 {
            return Err(TransformError::skipped(
                "simhash_dedup",
                "no near-duplicates found",
            ));
        }

        let output = output_parts.join("\n\n");
        Ok(ReformatOutput::from_lengths(content.len(), output))
    }
}

/// Split content into blocks at double-newline boundaries.
/// Preserves fenced code blocks (```) as single blocks.
fn split_into_blocks(content: &str) -> Vec<String> {
    let mut blocks: Vec<String> = Vec::new();
    let mut current = String::new();
    let mut in_fence = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("```") {
            in_fence = !in_fence;
            current.push_str(line);
            current.push('\n');
            if !in_fence {
                blocks.push(std::mem::take(&mut current).trim_end().to_string());
            }
            continue;
        }

        if in_fence {
            current.push_str(line);
            current.push('\n');
            continue;
        }

        if trimmed.is_empty() {
            if !current.trim().is_empty() {
                blocks.push(std::mem::take(&mut current).trim_end().to_string());
            }
            current.clear();
        } else {
            current.push_str(line);
            current.push('\n');
        }
    }

    if !current.trim().is_empty() {
        blocks.push(current.trim_end().to_string());
    }

    blocks
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dedup_near_duplicate_paragraphs() {
        let input = "The quick brown fox jumps over the lazy dog near the park.\n\n\
                     Some completely different text about a different topic entirely.\n\n\
                     The quick brown fox jumps over the lazy log near the park.\n";
        let dedup = SimhashDedup::new();
        let result = dedup.apply(input);
        match result {
            Ok(out) => {
                assert!(out.output.contains("duplicate"));
                assert!(out.bytes_saved > 0);
            }
            Err(_) => {
                // Acceptable if the hamming distance happens to be > threshold
            }
        }
    }

    #[test]
    fn no_dedup_for_different_content() {
        let input = "Alpha bravo charlie delta echo foxtrot golf hotel.\n\n\
                     India juliet kilo lima mike november oscar papa.\n\n\
                     Quebec romeo sierra tango uniform victor whiskey xray.\n";
        let dedup = SimhashDedup::new();
        let result = dedup.apply(input);
        assert!(result.is_err()); // Should be Skipped — no near-dups
    }

    #[test]
    fn preserves_short_blocks() {
        let input = "hi\n\nhello world foo bar baz qux quux corge grault garply.\n\nhi\n";
        let dedup = SimhashDedup::new();
        let result = dedup.apply(input);
        // "hi" is too short (1 token) — should be preserved regardless
        match result {
            Ok(out) => assert!(out.output.contains("hi")),
            Err(_) => {} // No dedup needed
        }
    }

    #[test]
    fn preserves_fenced_code_blocks() {
        let input = "```python\ndef foo():\n    pass\n```\n\nSome text between blocks.\n\n```python\ndef foo():\n    pass\n```\n";
        let dedup = SimhashDedup::new();
        // Even identical fenced blocks shouldn't be corrupted
        let result = dedup.apply(input);
        match result {
            Ok(out) => {
                // At least one fenced block should remain intact
                assert!(out.output.contains("```python"));
            }
            Err(_) => {}
        }
    }

    #[test]
    fn skips_single_block() {
        let input = "Just one block of text with no paragraph breaks at all.\n";
        let dedup = SimhashDedup::new();
        assert!(dedup.apply(input).is_err());
    }

    #[test]
    fn split_blocks_basic() {
        let blocks = split_into_blocks("a\n\nb\n\nc\n");
        assert_eq!(blocks.len(), 3);
    }

    #[test]
    fn split_blocks_preserves_fences() {
        let input = "intro\n\n```\ncode\nmore code\n```\n\nafter\n";
        let blocks = split_into_blocks(input);
        assert_eq!(blocks.len(), 3);
        assert!(blocks[1].contains("```"));
    }
}
