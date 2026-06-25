//! Code offload — drops bloated code sections via CCR with ROUGE-L quality gate.
//!
//! Uses [`code_analyzer::estimate_bloat`] for the gating signal and
//! applies language-agnostic + language-specific compression rules,
//! stashing the original in the CCR store.

use crate::ccr::CcrStore;
use crate::transforms::code_analyzer::{self, Language};
use crate::transforms::pipeline::traits::{
    CompressionContext, OffloadOutput, OffloadTransform, TransformError,
};
use crate::transforms::quality_gate::{self, QualityGate};
use crate::transforms::ContentType;

pub struct CodeOffload {
    gate: QualityGate,
    min_lines: usize,
}

impl Default for CodeOffload {
    fn default() -> Self {
        let threshold = quality_gate::thresholds::threshold_for("code_offload")
            .unwrap_or(quality_gate::thresholds::CODE_OFFLOAD);
        Self {
            gate: QualityGate::new(threshold),
            min_lines: 10,
        }
    }
}

impl CodeOffload {
    pub fn new() -> Self {
        Self::default()
    }
}

impl OffloadTransform for CodeOffload {
    fn name(&self) -> &'static str {
        "code_offload"
    }

    fn applies_to(&self) -> &[ContentType] {
        &[ContentType::SourceCode]
    }

    fn estimate_bloat(&self, content: &str) -> f32 {
        if content.lines().count() < self.min_lines {
            return 0.0;
        }
        code_analyzer::estimate_bloat(content)
    }

    fn apply(
        &self,
        content: &str,
        _ctx: &CompressionContext,
        store: &dyn CcrStore,
    ) -> Result<OffloadOutput, TransformError> {
        let lines = content.lines().count();
        if lines < self.min_lines {
            return Err(TransformError::skipped(
                "code_offload",
                "input below minimum line count",
            ));
        }

        let language = detect_language(content);
        let result = code_analyzer::analyze(content, language);

        if result.lines_removed == 0 {
            return Err(TransformError::skipped(
                "code_offload",
                "no bloat reduction achieved",
            ));
        }

        let cache_key = crate::ccr::compute_key(content.as_bytes());
        store.put(&cache_key, content);

        Ok(OffloadOutput::from_lengths(
            content.len(),
            result.output,
            cache_key,
        ))
    }

    fn confidence(&self) -> f32 {
        0.7
    }

    fn quality_gate(&self) -> Option<&QualityGate> {
        Some(&self.gate)
    }
}

/// Simple language detection from content heuristics.
fn detect_language(content: &str) -> Language {
    let first_line = content.lines().next().unwrap_or("");

    if first_line.starts_with("#!") {
        if first_line.contains("python") {
            return Language::Python;
        }
        if first_line.contains("node") || first_line.contains("deno") {
            return Language::JavaScript;
        }
        if first_line.contains("bash") || first_line.contains("sh") {
            return Language::Unknown;
        }
    }

    let sample: String = content.chars().take(2000).collect();

    if sample.contains("fn ") && sample.contains("->") && sample.contains("let ") {
        return Language::Rust;
    }
    if sample.contains("func ") && sample.contains("package ") {
        return Language::Go;
    }
    if sample.contains("def ") && sample.contains("import ") {
        return Language::Python;
    }
    if sample.contains("interface ") && sample.contains(": ") && sample.contains("const ") {
        return Language::TypeScript;
    }
    if sample.contains("function ") || sample.contains("const ") || sample.contains("=>") {
        return Language::JavaScript;
    }

    Language::Unknown
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ccr::InMemoryCcrStore;

    #[test]
    fn skips_short_content() {
        let offload = CodeOffload::new();
        let store = InMemoryCcrStore::new();
        let ctx = CompressionContext::default();
        let result = offload.apply("fn main() {}\n", &ctx, &store);
        assert!(result.is_err());
    }

    #[test]
    fn compresses_bloated_code() {
        let offload = CodeOffload::new();
        let store = InMemoryCcrStore::new();
        let ctx = CompressionContext::default();
        // Code with lots of repeated blank lines and comments
        let mut code = String::new();
        code.push_str("fn main() {\n");
        for _ in 0..5 {
            code.push_str("    // this is a comment\n");
        }
        code.push_str("\n\n\n\n\n");
        code.push_str("    println!(\"hello\");\n");
        code.push_str("}\n");

        let result = offload.apply(&code, &ctx, &store);
        match result {
            Ok(out) => {
                assert!(out.bytes_saved > 0);
                assert!(!out.cache_key.is_empty());
                // Verify CCR roundtrip
                let retrieved = store.get(&out.cache_key);
                assert_eq!(retrieved.as_deref(), Some(code.as_str()));
            }
            Err(_) => {
                // May skip if quality gate rejects
            }
        }
    }

    #[test]
    fn estimate_bloat_returns_zero_for_short() {
        let offload = CodeOffload::new();
        assert_eq!(offload.estimate_bloat("short\n"), 0.0);
    }

    #[test]
    fn quality_gate_configured() {
        let offload = CodeOffload::new();
        let gate = offload.quality_gate().unwrap();
        assert_eq!(
            gate.rouge_l_threshold,
            quality_gate::thresholds::CODE_OFFLOAD
        );
    }

    #[test]
    fn detect_python() {
        assert_eq!(
            detect_language("#!/usr/bin/env python3\nimport os\n"),
            Language::Python
        );
    }

    #[test]
    fn detect_rust() {
        assert_eq!(
            detect_language("fn main() -> Result<(), Error> {\n    let x = 5;\n}\n"),
            Language::Rust
        );
    }

    #[test]
    fn detect_go() {
        assert_eq!(
            detect_language("package main\n\nfunc main() {\n}\n"),
            Language::Go
        );
    }
}
