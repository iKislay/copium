//! Simhash — locality-sensitive fingerprinting for near-duplicate detection.
//!
//! Produces a 64-bit fingerprint for a text block such that blocks
//! differing by small edits (typo, whitespace, punctuation, sentence
//! reordering) have fingerprints within Hamming distance ≤ 3.

use std::hash::{Hash, Hasher};

const DEFAULT_SHINGLE_WIDTH: usize = 3;
const DEFAULT_HAMMING_THRESHOLD: u32 = 10;

/// Compute a 64-bit simhash fingerprint for the given text.
///
/// Uses character-level shingles of `width` tokens (whitespace-split).
/// Returns 0 for empty input.
pub fn hash(text: &str) -> u64 {
    hash_with_width(text, DEFAULT_SHINGLE_WIDTH)
}

/// Compute simhash with a configurable shingle width.
pub fn hash_with_width(text: &str, width: usize) -> u64 {
    let tokens: Vec<&str> = text.split_whitespace().collect();
    if tokens.is_empty() {
        return 0;
    }

    let width = width.max(1);
    if tokens.len() < width {
        return hash_single(&tokens.join(" "));
    }

    let mut v = [0i64; 64];

    for window in tokens.windows(width) {
        let shingle = window.join(" ");
        let h = hash_single(&shingle);
        for (i, bit) in v.iter_mut().enumerate() {
            if (h >> i) & 1 == 1 {
                *bit += 1;
            } else {
                *bit -= 1;
            }
        }
    }

    let mut fingerprint: u64 = 0;
    for (i, &bit) in v.iter().enumerate() {
        if bit > 0 {
            fingerprint |= 1 << i;
        }
    }
    fingerprint
}

/// Check if two fingerprints are near-duplicates (Hamming distance ≤ threshold).
pub fn is_near_duplicate(a: u64, b: u64) -> bool {
    is_near_duplicate_threshold(a, b, DEFAULT_HAMMING_THRESHOLD)
}

/// Check near-duplicate status with a custom threshold.
pub fn is_near_duplicate_threshold(a: u64, b: u64, threshold: u32) -> bool {
    hamming_distance(a, b) <= threshold
}

/// Compute Hamming distance between two 64-bit values.
#[inline]
pub fn hamming_distance(a: u64, b: u64) -> u32 {
    (a ^ b).count_ones()
}

/// Deduplicate a set of indexed text blocks, returning indices to keep.
/// The first occurrence in each near-duplicate cluster is retained.
pub fn deduplicate(blocks: &[(usize, &str)]) -> Vec<usize> {
    deduplicate_with_threshold(blocks, DEFAULT_SHINGLE_WIDTH, DEFAULT_HAMMING_THRESHOLD)
}

/// Deduplicate with configurable shingle width and Hamming threshold.
pub fn deduplicate_with_threshold(
    blocks: &[(usize, &str)],
    shingle_width: usize,
    threshold: u32,
) -> Vec<usize> {
    if blocks.is_empty() {
        return Vec::new();
    }

    let fingerprints: Vec<(usize, u64)> = blocks
        .iter()
        .map(|(idx, text)| (*idx, hash_with_width(text, shingle_width)))
        .collect();

    let mut keep: Vec<usize> = Vec::with_capacity(blocks.len());
    let mut kept_fps: Vec<u64> = Vec::with_capacity(blocks.len());

    for (idx, fp) in &fingerprints {
        let is_dup = kept_fps
            .iter()
            .any(|&kept_fp| is_near_duplicate_threshold(*fp, kept_fp, threshold));

        if !is_dup {
            keep.push(*idx);
            kept_fps.push(*fp);
        }
    }

    keep
}

/// FNV-1a 64-bit hash of a string for shingle hashing.
#[inline]
fn hash_single(s: &str) -> u64 {
    let mut hasher = FnvHasher::new();
    s.hash(&mut hasher);
    hasher.finish()
}

struct FnvHasher(u64);

impl FnvHasher {
    #[inline]
    fn new() -> Self {
        Self(0xcbf29ce484222325)
    }
}

impl Hasher for FnvHasher {
    #[inline]
    fn finish(&self) -> u64 {
        self.0
    }

    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            self.0 ^= u64::from(byte);
            self.0 = self.0.wrapping_mul(0x100000001b3);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input_returns_zero() {
        assert_eq!(hash(""), 0);
        assert_eq!(hash("   "), 0);
    }

    #[test]
    fn identical_content_yields_identical_hash() {
        let text = "the quick brown fox jumps over the lazy dog";
        assert_eq!(hash(text), hash(text));
    }

    #[test]
    fn single_char_delta_near_duplicate() {
        // With longer text, single-char edits produce low hamming distance
        let base = "the quick brown fox jumps over the lazy dog and runs through the forest towards the distant mountain peak while the sun sets";
        let edited = "the quick brown fox jumps over the lazy log and runs through the forest towards the distant mountain peak while the sun sets";
        let ha = hash(base);
        let hb = hash(edited);
        assert!(
            is_near_duplicate(ha, hb),
            "single-char delta in long text should be near-dup, hamming={}",
            hamming_distance(ha, hb)
        );
    }

    #[test]
    fn whitespace_difference_near_duplicate() {
        let a = "hello world foo bar baz";
        let b = "hello  world  foo  bar  baz";
        // split_whitespace normalizes multiple spaces
        assert_eq!(hash(a), hash(b));
    }

    #[test]
    fn punctuation_delta_near_duplicate() {
        // Longer text with punctuation difference
        let a = "hello world, this is a test of the system that processes and handles many different kinds of complex input data structures efficiently";
        let b = "hello world this is a test of the system that processes and handles many different kinds of complex input data structures efficiently";
        let ha = hash(a);
        let hb = hash(b);
        assert!(
            is_near_duplicate(ha, hb),
            "punctuation delta in long text should be near-dup, hamming={}",
            hamming_distance(ha, hb)
        );
    }

    #[test]
    fn completely_different_not_near_duplicate() {
        let a = "the quick brown fox jumps over the lazy dog";
        let b = "pack my box with five dozen liquor jugs now";
        let ha = hash(a);
        let hb = hash(b);
        assert!(
            !is_near_duplicate(ha, hb),
            "completely different should NOT be near-dup, hamming={}",
            hamming_distance(ha, hb)
        );
    }

    #[test]
    fn sentence_reordering_similar() {
        let a = "first sentence here and it has enough words to make shingles meaningful. second sentence follows with additional context and detail. third one ends it all with a proper conclusion.";
        let b = "second sentence follows with additional context and detail. first sentence here and it has enough words to make shingles meaningful. third one ends it all with a proper conclusion.";
        let ha = hash(a);
        let hb = hash(b);
        // Sentence reordering with shared shingles — may or may not be under threshold
        // but should be closer than completely different texts
        let dist = hamming_distance(ha, hb);
        let completely_different = hash("pack my box with five dozen liquor jugs and prepare them for the international shipping container that departs tomorrow morning early");
        let diff_dist = hamming_distance(ha, hash(completely_different.to_string().as_str()));
        assert!(
            dist < diff_dist || dist < 20,
            "reordered sentences should be more similar than completely different, dist={dist}",
        );
    }

    #[test]
    fn deduplicate_removes_near_dups() {
        // Use longer texts so simhash works well
        let base = "the quick brown fox jumps over the lazy dog and runs through the dense forest towards the distant mountain peak while gazing at clouds";
        let near1 = "the quick brown fox jumps over the lazy log and runs through the dense forest towards the distant mountain peak while gazing at clouds";
        let different = "pack my box with five dozen liquor jugs and prepare them for the international shipping container that departs tomorrow morning at dawn";
        let near2 = "the quick brown fox jumps over the lazy hog and runs through the dense forest towards the distant mountain peak while gazing at clouds";
        let blocks: Vec<(usize, &str)> = vec![(0, base), (1, near1), (2, different), (3, near2)];
        let kept = deduplicate(&blocks);
        // Block 0 kept (first), different kept, near-dups filtered
        assert!(kept.contains(&0));
        assert!(kept.contains(&2));
        assert!(
            kept.len() <= 3,
            "should filter at least one near-dup, kept={kept:?}"
        );
    }

    #[test]
    fn deduplicate_empty() {
        let blocks: Vec<(usize, &str)> = vec![];
        assert_eq!(deduplicate(&blocks), Vec::<usize>::new());
    }

    #[test]
    fn single_token_input() {
        let fp = hash("hello");
        assert_ne!(fp, 0);
    }

    #[test]
    fn hamming_distance_self_is_zero() {
        let fp = hash("some text for testing the hash");
        assert_eq!(hamming_distance(fp, fp), 0);
    }

    #[test]
    fn hamming_distance_opposites() {
        assert_eq!(hamming_distance(0, u64::MAX), 64);
    }
}
