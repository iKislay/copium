//! Position-aware weight configuration.
//!
//! Controls how strongly position information influences compression
//! decisions. The default (`position_weight = 0.0`) disables position
//! awareness entirely, preserving backwards compatibility.

/// Configuration for position-aware compression behavior.
#[derive(Debug, Clone)]
pub struct PositionWeightConfig {
    /// Master weight for position influence. Range: [0.0, 1.0].
    /// - 0.0: Position is ignored (backwards-compatible default).
    /// - 1.0: Full position weighting applied.
    pub position_weight: f64,

    /// Bonus applied when moving important content from the degraded
    /// middle zone to a high-attention zone (beginning or end).
    pub middle_to_edge_bonus: f64,

    /// Penalty applied when content would move from a high-attention
    /// zone into the degraded middle zone.
    pub edge_to_middle_penalty: f64,

    /// Small bonus for content that stays in a high-attention zone.
    pub stable_high_attention_bonus: f64,

    /// Whether to enable intra-block reordering to move important
    /// items toward the edges of compressed blocks.
    pub enable_reordering: bool,

    /// Maximum fraction of items that can be reordered within a block.
    /// Limits disruption of chronological order. Range: [0.0, 1.0].
    pub max_reorder_fraction: f64,
}

impl Default for PositionWeightConfig {
    fn default() -> Self {
        PositionWeightConfig {
            position_weight: 0.0,
            middle_to_edge_bonus: 0.3,
            edge_to_middle_penalty: -0.2,
            stable_high_attention_bonus: 0.05,
            enable_reordering: false,
            max_reorder_fraction: 0.5,
        }
    }
}

impl PositionWeightConfig {
    /// Returns true if position awareness is effectively disabled.
    pub fn is_disabled(&self) -> bool {
        self.position_weight == 0.0
    }

    /// Create a config with position awareness enabled at the given weight.
    pub fn enabled(weight: f64) -> Self {
        PositionWeightConfig {
            position_weight: weight.clamp(0.0, 1.0),
            enable_reordering: weight > 0.0,
            ..Default::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_is_disabled() {
        let config = PositionWeightConfig::default();
        assert!(config.is_disabled());
        assert_eq!(config.position_weight, 0.0);
        assert!(!config.enable_reordering);
    }

    #[test]
    fn test_enabled_constructor() {
        let config = PositionWeightConfig::enabled(0.5);
        assert!(!config.is_disabled());
        assert_eq!(config.position_weight, 0.5);
        assert!(config.enable_reordering);
    }

    #[test]
    fn test_weight_clamping() {
        let config = PositionWeightConfig::enabled(2.0);
        assert_eq!(config.position_weight, 1.0);

        let config = PositionWeightConfig::enabled(-1.0);
        assert_eq!(config.position_weight, 0.0);
    }
}
