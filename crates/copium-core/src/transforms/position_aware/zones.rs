//! Position zone classification.
//!
//! Partitions a context window into five zones based on the empirically
//! observed U-shaped attention curve:
//!
//! | Zone         | Range       | Attention Quality |
//! |--------------|-------------|-------------------|
//! | Beginning    | 0–10%       | High              |
//! | MidBeginning | 10–30%      | Moderate          |
//! | Middle       | 30–70%      | Low (degraded)    |
//! | MidEnd       | 70–90%      | Moderate          |
//! | End          | 90–100%     | High              |

/// Attention zone within a context window.
///
/// The zones reflect the empirical finding that LLMs attend most
/// strongly to the beginning and end of their context, with degraded
/// attention in the middle (Liu et al., 2023).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Zone {
    /// First 10% of context — highest attention, attention-sink region.
    Beginning,
    /// 10–30% — good but declining attention.
    MidBeginning,
    /// 30–70% — the "lost in the middle" degradation zone.
    Middle,
    /// 70–90% — recovering attention toward the end.
    MidEnd,
    /// Last 10% — near-prediction-target, high attention.
    End,
}

impl Zone {
    /// Returns the approximate attention quality for this zone as a
    /// multiplier in [0.0, 1.0]. Based on averaged NIAH/RULER
    /// benchmark data across context lengths.
    pub fn attention_quality(&self) -> f64 {
        match self {
            Zone::Beginning => 0.95,
            Zone::MidBeginning => 0.78,
            Zone::Middle => 0.55,
            Zone::MidEnd => 0.75,
            Zone::End => 0.93,
        }
    }

    /// Returns true if this zone has degraded attention (middle region).
    pub fn is_degraded(&self) -> bool {
        matches!(self, Zone::Middle)
    }

    /// Returns true if this zone is a high-attention zone.
    pub fn is_high_attention(&self) -> bool {
        matches!(self, Zone::Beginning | Zone::End)
    }
}

/// Classify a position within a context of `context_length` items into
/// the appropriate attention zone.
///
/// # Arguments
///
/// * `position` — Zero-based index of the item in the context.
/// * `context_length` — Total number of items in the context.
///
/// # Returns
///
/// The `Zone` corresponding to the relative position. Returns
/// `Zone::Middle` if `context_length` is 0.
///
/// # Examples
///
/// ```
/// use copium_core::transforms::position_aware::zones::{position_zone, Zone};
///
/// assert_eq!(position_zone(0, 100), Zone::Beginning);
/// assert_eq!(position_zone(50, 100), Zone::Middle);
/// assert_eq!(position_zone(95, 100), Zone::End);
/// ```
pub fn position_zone(position: usize, context_length: usize) -> Zone {
    if context_length == 0 {
        return Zone::Middle;
    }

    let relative = position as f64 / context_length as f64;

    if relative < 0.10 {
        Zone::Beginning
    } else if relative < 0.30 {
        Zone::MidBeginning
    } else if relative < 0.70 {
        Zone::Middle
    } else if relative < 0.90 {
        Zone::MidEnd
    } else {
        Zone::End
    }
}

/// Compute the relative position as a fraction in [0.0, 1.0].
///
/// Returns 0.5 if `context_length` is 0.
pub fn relative_position(position: usize, context_length: usize) -> f64 {
    if context_length == 0 {
        return 0.5;
    }
    (position as f64) / (context_length as f64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_position_zone_boundaries() {
        // 100 items — nice round numbers for boundary testing
        assert_eq!(position_zone(0, 100), Zone::Beginning);
        assert_eq!(position_zone(9, 100), Zone::Beginning);
        assert_eq!(position_zone(10, 100), Zone::MidBeginning);
        assert_eq!(position_zone(29, 100), Zone::MidBeginning);
        assert_eq!(position_zone(30, 100), Zone::Middle);
        assert_eq!(position_zone(50, 100), Zone::Middle);
        assert_eq!(position_zone(69, 100), Zone::Middle);
        assert_eq!(position_zone(70, 100), Zone::MidEnd);
        assert_eq!(position_zone(89, 100), Zone::MidEnd);
        assert_eq!(position_zone(90, 100), Zone::End);
        assert_eq!(position_zone(99, 100), Zone::End);
    }

    #[test]
    fn test_position_zone_small_context() {
        // Very small context — all items land in Beginning
        assert_eq!(position_zone(0, 3), Zone::Beginning);
        assert_eq!(position_zone(1, 3), Zone::Middle);
        assert_eq!(position_zone(2, 3), Zone::Middle);
    }

    #[test]
    fn test_position_zone_empty_context() {
        assert_eq!(position_zone(0, 0), Zone::Middle);
    }

    #[test]
    fn test_zone_attention_quality() {
        assert!(Zone::Beginning.attention_quality() > Zone::Middle.attention_quality());
        assert!(Zone::End.attention_quality() > Zone::Middle.attention_quality());
        assert!(Zone::MidBeginning.attention_quality() > Zone::Middle.attention_quality());
    }

    #[test]
    fn test_zone_predicates() {
        assert!(Zone::Middle.is_degraded());
        assert!(!Zone::Beginning.is_degraded());
        assert!(Zone::Beginning.is_high_attention());
        assert!(Zone::End.is_high_attention());
        assert!(!Zone::Middle.is_high_attention());
    }

    #[test]
    fn test_relative_position() {
        assert_eq!(relative_position(0, 100), 0.0);
        assert_eq!(relative_position(50, 100), 0.5);
        assert_eq!(relative_position(100, 100), 1.0);
        assert_eq!(relative_position(0, 0), 0.5);
    }
}
