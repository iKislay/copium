//! Quality gate — post-compression semantic preservation validation.
//!
//! When an [`OffloadTransform`] produces a candidate output, the quality
//! gate validates that the candidate preserves sufficient semantic content
//! from the original via ROUGE-L scoring before the orchestrator commits
//! to CCR stash + marker emission. If the gate fails, the candidate is
//! discarded and the original passes through unchanged.

pub mod rouge_l;
pub mod thresholds;

pub use rouge_l::{rouge_l, rouge_l_str};

/// Metric used for quality assessment.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QualityMetric {
    RougeL,
    BertScore,
}

/// Result of a quality gate check.
#[derive(Debug, Clone)]
pub enum GateResult {
    Pass {
        score: f32,
        metric: QualityMetric,
    },
    Fail {
        score: f32,
        metric: QualityMetric,
        reason: String,
    },
}

impl GateResult {
    pub fn is_pass(&self) -> bool {
        matches!(self, GateResult::Pass { .. })
    }
}

/// Configuration for quality validation of an offload transform's output.
#[derive(Debug, Clone)]
pub struct QualityGate {
    pub rouge_l_threshold: f32,
    pub bert_score_threshold: f32,
    pub metric: QualityMetric,
    pub max_compression_ratio: f32,
}

impl QualityGate {
    pub fn new(rouge_l_threshold: f32) -> Self {
        Self {
            rouge_l_threshold,
            bert_score_threshold: 0.0,
            metric: QualityMetric::RougeL,
            max_compression_ratio: 10.0,
        }
    }

    pub fn with_metric(mut self, metric: QualityMetric) -> Self {
        self.metric = metric;
        self
    }

    pub fn with_max_compression_ratio(mut self, ratio: f32) -> Self {
        self.max_compression_ratio = ratio;
        self
    }

    /// Validate that `candidate` preserves sufficient semantic content
    /// from `original`. For large inputs (>5KB), samples first 2KB + last
    /// 1KB unless max_compression_ratio < 1.1 (barely compressing —
    /// validate fully).
    pub fn validate(&self, original: &str, candidate: &str) -> GateResult {
        if original.is_empty() && candidate.is_empty() {
            return GateResult::Pass {
                score: 1.0,
                metric: self.metric,
            };
        }

        if candidate == original {
            return GateResult::Pass {
                score: 1.0,
                metric: self.metric,
            };
        }

        let compression_ratio = if candidate.is_empty() {
            f32::INFINITY
        } else {
            original.len() as f32 / candidate.len() as f32
        };

        if compression_ratio > self.max_compression_ratio {
            return GateResult::Fail {
                score: 0.0,
                metric: self.metric,
                reason: format!(
                    "compression ratio {compression_ratio:.2} exceeds max {}",
                    self.max_compression_ratio
                ),
            };
        }

        let (ref_sample, cand_sample) =
            if original.len() > 5120 && self.max_compression_ratio >= 1.1 {
                (sample_text(original), sample_text(candidate))
            } else {
                (original.to_string(), candidate.to_string())
            };

        let score = rouge_l_str(&ref_sample, &cand_sample);

        let threshold = match self.metric {
            QualityMetric::RougeL => self.rouge_l_threshold,
            QualityMetric::BertScore => self.bert_score_threshold,
        };

        if score >= threshold {
            GateResult::Pass {
                score,
                metric: self.metric,
            }
        } else {
            GateResult::Fail {
                score,
                metric: self.metric,
                reason: format!("score {score:.4} below threshold {threshold:.4}"),
            }
        }
    }
}

/// Sample first 2KB + last 1KB for large inputs.
fn sample_text(text: &str) -> String {
    let bytes = text.as_bytes();
    if bytes.len() <= 3072 {
        return text.to_string();
    }

    let first_end = find_char_boundary(text, 2048);
    let last_start = find_char_boundary_rev(text, 1024);

    let mut sampled = String::with_capacity(3072);
    sampled.push_str(&text[..first_end]);
    sampled.push(' ');
    sampled.push_str(&text[last_start..]);
    sampled
}

/// Find the nearest char boundary at or before `target_byte`.
fn find_char_boundary(text: &str, target_byte: usize) -> usize {
    let target = target_byte.min(text.len());
    let mut pos = target;
    while pos > 0 && !text.is_char_boundary(pos) {
        pos -= 1;
    }
    pos
}

/// Find the nearest char boundary for the last `target_bytes` of text.
fn find_char_boundary_rev(text: &str, target_bytes: usize) -> usize {
    if target_bytes >= text.len() {
        return 0;
    }
    let mut pos = text.len() - target_bytes;
    while pos < text.len() && !text.is_char_boundary(pos) {
        pos += 1;
    }
    pos
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gate_pass_identical() {
        let gate = QualityGate::new(0.75);
        let result = gate.validate("hello world", "hello world");
        assert!(result.is_pass());
    }

    #[test]
    fn gate_pass_both_empty() {
        let gate = QualityGate::new(0.75);
        let result = gate.validate("", "");
        assert!(result.is_pass());
    }

    #[test]
    fn gate_fail_too_aggressive() {
        let gate = QualityGate::new(0.90);
        let original = "the quick brown fox jumps over the lazy dog";
        let candidate = "fox dog";
        let result = gate.validate(original, candidate);
        assert!(!result.is_pass());
    }

    #[test]
    fn gate_pass_good_compression() {
        let gate = QualityGate::new(0.60);
        let original = "the quick brown fox jumps over the lazy dog near the park";
        let candidate = "the quick brown fox jumps over the lazy dog";
        let result = gate.validate(original, candidate);
        assert!(result.is_pass());
    }

    #[test]
    fn gate_fail_compression_ratio_exceeded() {
        let gate = QualityGate::new(0.5).with_max_compression_ratio(2.0);
        let original = "a ".repeat(1000);
        let candidate = "a";
        let result = gate.validate(&original, candidate);
        assert!(!result.is_pass());
    }

    #[test]
    fn gate_samples_large_input() {
        let gate = QualityGate::new(0.3);
        let original = "word ".repeat(2000); // ~10KB
        let candidate = "word ".repeat(1500);
        // Should sample and still pass since content is similar
        let result = gate.validate(&original, &candidate);
        assert!(result.is_pass());
    }
}
