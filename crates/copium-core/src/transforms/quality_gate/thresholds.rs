//! Per-transform ROUGE-L threshold constants.
//!
//! Calibrated per plan §6.2 phase 3. Each offload has a different
//! acceptable semantic loss profile based on the content type it
//! operates on. Overridable via environment variables for ops tuning.

/// JsonOffload: structured data where key preservation is critical.
pub const JSON_OFFLOAD: f32 = 0.75;

/// LogOffload: repetitive content where pattern preservation matters.
pub const LOG_OFFLOAD: f32 = 0.65;

/// DiffOffload: context-heavy diffs where changes must survive.
pub const DIFF_OFFLOAD: f32 = 0.60;

/// SearchOffload: ranked results where top matches are essential.
pub const SEARCH_OFFLOAD: f32 = 0.70;

/// DiffNoise: noise removal where most content should be preserved.
pub const DIFF_NOISE: f32 = 0.80;

/// CodeOffload: code where identifiers and structure are paramount.
pub const CODE_OFFLOAD: f32 = 0.80;

/// Read a threshold override from the environment.
/// Env var format: `COPIUM_ROUGE_THRESHOLD_<UPPER_SNAKE_NAME>`
pub fn threshold_for(name: &str) -> Option<f32> {
    let env_key = format!(
        "COPIUM_ROUGE_THRESHOLD_{}",
        name.to_uppercase().replace('-', "_")
    );
    std::env::var(env_key).ok().and_then(|v| v.parse().ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn threshold_values_match_spec() {
        assert_eq!(JSON_OFFLOAD, 0.75);
        assert_eq!(LOG_OFFLOAD, 0.65);
        assert_eq!(DIFF_OFFLOAD, 0.60);
        assert_eq!(SEARCH_OFFLOAD, 0.70);
        assert_eq!(DIFF_NOISE, 0.80);
        assert_eq!(CODE_OFFLOAD, 0.80);
    }

    #[test]
    fn threshold_for_missing_env() {
        assert_eq!(threshold_for("nonexistent_transform"), None);
    }
}
