//! Position-aware compression primitives.
//!
//! Addresses the "Lost in the Middle" problem (Liu et al., 2023): LLMs
//! degrade at retrieving information from the middle of their context
//! window. This module provides utilities for:
//!
//! - Classifying positions into attention zones (beginning, mid-beginning,
//!   middle, mid-end, end)
//! - Computing position-dependent importance weights
//! - Optimizing item ordering within compressed blocks to maximize
//!   retrievability of high-importance content
//!
//! # Design principle
//!
//! Position awareness is additive — when `position_weight = 0.0` (the
//! default), all functions reduce to no-ops or identity transforms.
//! Existing compression behavior is unchanged unless the user opts in.

pub mod config;
pub mod scoring;
pub mod zones;

pub use config::PositionWeightConfig;
pub use scoring::{compute_position_benefit, position_weighted_score};
pub use zones::{position_zone, Zone};
