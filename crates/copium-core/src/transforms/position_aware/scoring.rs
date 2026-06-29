//! Position-aware scoring functions.
//!
//! Extends content-based importance scoring with position-dependent
//! weights that account for the U-shaped attention degradation curve
//! in transformer-based LLMs.

use super::config::PositionWeightConfig;
use super::zones::{position_zone, Zone};

/// Compute the benefit (or penalty) of placing content at a given
/// target position, given its original position in the context.
///
/// Returns a value in approximately [-0.2, 0.3] representing how
/// much the position change benefits retrievability:
/// - Positive: content moves to a better attention zone
/// - Zero: no meaningful change
/// - Negative: content moves to a worse attention zone
///
/// # Arguments
///
/// * `original_pos` — Original zero-based position in the uncompressed context
/// * `target_pos` — Target position in the compressed/reordered output
/// * `context_len` — Total context length (for zone computation)
/// * `config` — Position weight configuration
pub fn compute_position_benefit(
    original_pos: usize,
    target_pos: usize,
    context_len: usize,
    config: &PositionWeightConfig,
) -> f64 {
    if config.is_disabled() {
        return 0.0;
    }

    let original_zone = position_zone(original_pos, context_len);
    let target_zone = position_zone(target_pos, context_len);

    let raw_benefit = match (original_zone, target_zone) {
        // Moving from degraded middle to high-attention edges
        (Zone::Middle, Zone::Beginning | Zone::End) => config.middle_to_edge_bonus,
        // Moving from middle to moderate zones — partial improvement
        (Zone::Middle, Zone::MidBeginning | Zone::MidEnd) => config.middle_to_edge_bonus * 0.5,
        // Staying in the middle — no change
        (Zone::Middle, Zone::Middle) => 0.0,
        // Moving from high-attention to middle — bad
        (Zone::Beginning | Zone::End, Zone::Middle) => config.edge_to_middle_penalty,
        // Moving from moderate to middle — slightly bad
        (Zone::MidBeginning | Zone::MidEnd, Zone::Middle) => config.edge_to_middle_penalty * 0.5,
        // Staying in high-attention zones — small bonus
        (Zone::Beginning, Zone::Beginning) | (Zone::End, Zone::End) => {
            config.stable_high_attention_bonus
        }
        // All other transitions — neutral
        _ => 0.0,
    };

    raw_benefit * config.position_weight
}

/// Compute a position-weighted importance score that combines content
/// relevance with position-dependent attention quality.
///
/// The formula is:
///   `base_score * (1.0 + position_benefit * position_weight)`
///
/// When `position_weight = 0.0`, returns `base_score` unchanged.
///
/// # Arguments
///
/// * `base_score` — Content-based importance score (e.g., from BM25 or
///   information density scoring). Should be in [0.0, 1.0].
/// * `original_pos` — Original position in context
/// * `target_pos` — Target position after compression/reordering
/// * `context_len` — Total context length
/// * `config` — Position weight configuration
pub fn position_weighted_score(
    base_score: f64,
    original_pos: usize,
    target_pos: usize,
    context_len: usize,
    config: &PositionWeightConfig,
) -> f64 {
    if config.is_disabled() {
        return base_score;
    }

    let benefit = compute_position_benefit(original_pos, target_pos, context_len, config);
    let weighted = base_score * (1.0 + benefit);
    weighted.max(0.0) // Never produce negative scores
}

/// Score how much an item at `position` would benefit from being kept
/// vs. removed, considering its position in the attention curve.
///
/// Items in the degraded middle zone get a lower "keep priority" since
/// keeping them provides less value (the model is less likely to attend
/// to them). Items at edges get a higher keep priority.
///
/// Returns a multiplier in [0.5, 1.2] to apply to content scores.
pub fn position_keep_priority(position: usize, context_len: usize) -> f64 {
    let zone = position_zone(position, context_len);
    zone.attention_quality()
}

/// Optimize the ordering of kept items within a compressed block to
/// maximize retrievability. Places high-importance items at the
/// beginning and end of the block (high-attention zones), while
/// lower-importance items go in the middle.
///
/// This implements the "bookend" strategy: the most important items
/// are placed at position 0 and N-1, the next most important at
/// positions 1 and N-2, etc.
///
/// # Arguments
///
/// * `items_with_scores` — Pairs of (original_index, importance_score)
/// * `config` — Position weight configuration
///
/// # Returns
///
/// Reordered vector of original indices. If reordering is disabled or
/// `position_weight = 0.0`, returns indices in their original order.
pub fn optimize_kept_order(
    items_with_scores: &[(usize, f64)],
    config: &PositionWeightConfig,
) -> Vec<usize> {
    if config.is_disabled() || !config.enable_reordering || items_with_scores.is_empty() {
        return items_with_scores.iter().map(|(idx, _)| *idx).collect();
    }

    let n = items_with_scores.len();
    if n <= 2 {
        // Nothing meaningful to reorder
        return items_with_scores.iter().map(|(idx, _)| *idx).collect();
    }

    // Limit how many items we actually reorder
    let max_reorder = ((n as f64) * config.max_reorder_fraction).ceil() as usize;
    let reorder_count = max_reorder.min(n);

    // Sort by score descending to identify the most important items
    let mut scored: Vec<(usize, f64)> = items_with_scores.to_vec();
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Split into items that will be reordered (top N by score) and
    // items that keep their relative position (the rest)
    let to_reorder: Vec<(usize, f64)> = scored[..reorder_count].to_vec();
    let keep_in_place: Vec<usize> = scored[reorder_count..].iter().map(|(idx, _)| *idx).collect();

    // Apply bookend strategy to the reordered items:
    // Highest score → position 0 (beginning of block)
    // Second highest → last position (end of block)
    // Third highest → position 1
    // Fourth highest → second-to-last
    // etc.
    let mut result = vec![0usize; reorder_count];
    let mut front = 0;
    let mut back = reorder_count - 1;
    let mut place_front = true;

    for (idx, _) in &to_reorder {
        if place_front {
            result[front] = *idx;
            front += 1;
        } else {
            result[back] = *idx;
            if back > 0 {
                back -= 1;
            }
        }
        place_front = !place_front;
    }

    // Merge: reordered items first, then the rest in original order
    let mut keep_sorted = keep_in_place;
    keep_sorted.sort();
    result.extend(keep_sorted);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_position_benefit_disabled() {
        let config = PositionWeightConfig::default();
        assert_eq!(compute_position_benefit(50, 5, 100, &config), 0.0);
    }

    #[test]
    fn test_compute_position_benefit_middle_to_beginning() {
        let config = PositionWeightConfig::enabled(1.0);
        let benefit = compute_position_benefit(50, 5, 100, &config);
        assert!(benefit > 0.0, "Moving from middle to beginning should be positive");
        assert_eq!(benefit, 0.3);
    }

    #[test]
    fn test_compute_position_benefit_beginning_to_middle() {
        let config = PositionWeightConfig::enabled(1.0);
        let benefit = compute_position_benefit(5, 50, 100, &config);
        assert!(benefit < 0.0, "Moving from beginning to middle should be negative");
        assert_eq!(benefit, -0.2);
    }

    #[test]
    fn test_compute_position_benefit_stays_middle() {
        let config = PositionWeightConfig::enabled(1.0);
        let benefit = compute_position_benefit(40, 60, 100, &config);
        assert_eq!(benefit, 0.0);
    }

    #[test]
    fn test_position_weighted_score_disabled() {
        let config = PositionWeightConfig::default();
        let score = position_weighted_score(0.8, 50, 5, 100, &config);
        assert_eq!(score, 0.8); // Unchanged when disabled
    }

    #[test]
    fn test_position_weighted_score_enabled() {
        let config = PositionWeightConfig::enabled(1.0);
        // Item moves from middle (pos 50) to beginning (pos 5) in 100 items
        let score = position_weighted_score(0.8, 50, 5, 100, &config);
        // 0.8 * (1.0 + 0.3) = 1.04
        assert!((score - 1.04).abs() < 1e-10);
    }

    #[test]
    fn test_position_weighted_score_never_negative() {
        let config = PositionWeightConfig::enabled(1.0);
        // Even with a strong penalty, score shouldn't go negative
        let score = position_weighted_score(0.1, 5, 50, 100, &config);
        assert!(score >= 0.0);
    }

    #[test]
    fn test_optimize_kept_order_disabled() {
        let config = PositionWeightConfig::default();
        let items = vec![(0, 0.9), (1, 0.5), (2, 0.7), (3, 0.3)];
        let result = optimize_kept_order(&items, &config);
        assert_eq!(result, vec![0, 1, 2, 3]);
    }

    #[test]
    fn test_optimize_kept_order_bookend() {
        let config = PositionWeightConfig {
            position_weight: 1.0,
            enable_reordering: true,
            max_reorder_fraction: 1.0,
            ..Default::default()
        };
        let items = vec![(0, 0.2), (1, 0.9), (2, 0.5), (3, 0.8)];
        let result = optimize_kept_order(&items, &config);
        // Highest score (1, 0.9) should be at position 0
        // Second highest (3, 0.8) should be at end
        assert_eq!(result[0], 1);
        assert_eq!(result[result.len() - 1], 3);
    }

    #[test]
    fn test_optimize_kept_order_empty() {
        let config = PositionWeightConfig::enabled(1.0);
        let items: Vec<(usize, f64)> = vec![];
        let result = optimize_kept_order(&items, &config);
        assert!(result.is_empty());
    }

    #[test]
    fn test_position_keep_priority_edges_higher() {
        let beginning_priority = position_keep_priority(5, 100);
        let middle_priority = position_keep_priority(50, 100);
        let end_priority = position_keep_priority(95, 100);

        assert!(beginning_priority > middle_priority);
        assert!(end_priority > middle_priority);
    }
}
