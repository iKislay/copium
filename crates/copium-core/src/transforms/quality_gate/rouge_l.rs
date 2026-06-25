use unicode_normalization::UnicodeNormalization;

/// Compute ROUGE-L F-measure between a reference and candidate token sequence.
///
/// Uses LCS (Longest Common Subsequence) with O(n·m) DP and O(min(n,m))
/// rolling-array space. Tokens are NFC-normalized for stable byte comparison.
///
/// Returns a value in [0.0, 1.0]:
/// - Both empty → 1.0 (identity convention)
/// - One empty, other non-empty → 0.0
/// - Otherwise: F = 2·R·P / (R+P) where R = LCS/|ref|, P = LCS/|cand|
pub fn rouge_l(reference: &[&str], candidate: &[&str]) -> f32 {
    if reference.is_empty() && candidate.is_empty() {
        return 1.0;
    }
    if reference.is_empty() || candidate.is_empty() {
        return 0.0;
    }

    let lcs_len = lcs_length(reference, candidate);

    let r = lcs_len as f64 / reference.len() as f64;
    let p = lcs_len as f64 / candidate.len() as f64;

    if r + p == 0.0 {
        return 0.0;
    }

    let f = 2.0 * r * p / (r + p);
    f as f32
}

/// Compute ROUGE-L from raw strings, tokenizing by whitespace and
/// NFC-normalizing each token before comparison.
pub fn rouge_l_str(reference: &str, candidate: &str) -> f32 {
    let ref_tokens: Vec<String> = tokenize_nfc(reference);
    let cand_tokens: Vec<String> = tokenize_nfc(candidate);

    let ref_slices: Vec<&str> = ref_tokens.iter().map(|s| s.as_str()).collect();
    let cand_slices: Vec<&str> = cand_tokens.iter().map(|s| s.as_str()).collect();

    rouge_l(&ref_slices, &cand_slices)
}

/// LCS length via DP with O(min(n,m)) rolling-array space.
fn lcs_length(a: &[&str], b: &[&str]) -> usize {
    let (short, long) = if a.len() <= b.len() { (a, b) } else { (b, a) };
    let n = short.len();

    let mut prev = vec![0usize; n + 1];
    let mut curr = vec![0usize; n + 1];

    for long_tok in long {
        for (j, short_tok) in short.iter().enumerate() {
            if tokens_equal(long_tok, short_tok) {
                curr[j + 1] = prev[j] + 1;
            } else {
                curr[j + 1] = curr[j].max(prev[j + 1]);
            }
        }
        std::mem::swap(&mut prev, &mut curr);
        curr.iter_mut().for_each(|x| *x = 0);
    }

    *prev.iter().max().unwrap_or(&0)
}

/// NFC-normalize and compare two tokens.
#[inline]
fn tokens_equal(a: &str, b: &str) -> bool {
    // Fast path: if bytes are equal, skip NFC normalization.
    if a == b {
        return true;
    }
    let a_nfc: String = a.nfc().collect();
    let b_nfc: String = b.nfc().collect();
    a_nfc == b_nfc
}

/// Tokenize a string by whitespace, returning NFC-normalized tokens.
fn tokenize_nfc(text: &str) -> Vec<String> {
    text.split_whitespace()
        .map(|tok| tok.nfc().collect::<String>())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn both_empty_returns_one() {
        let empty: &[&str] = &[];
        assert_eq!(rouge_l(empty, empty), 1.0);
    }

    #[test]
    fn empty_reference_non_empty_candidate() {
        let empty: &[&str] = &[];
        assert_eq!(rouge_l(empty, &["hello", "world"]), 0.0);
    }

    #[test]
    fn non_empty_reference_empty_candidate() {
        let empty: &[&str] = &[];
        assert_eq!(rouge_l(&["hello", "world"], empty), 0.0);
    }

    #[test]
    fn identical_sequences() {
        let tokens = &["the", "cat", "sat", "on", "the", "mat"];
        assert_eq!(rouge_l(tokens, tokens), 1.0);
    }

    #[test]
    fn substring_sequence() {
        // reference is a subsequence of candidate
        let reference = &["cat", "sat"];
        let candidate = &["the", "cat", "sat", "on", "the", "mat"];
        // LCS = 2, R = 2/2 = 1.0, P = 2/6 = 0.333..
        // F = 2 * 1.0 * 0.333 / (1.0 + 0.333) = 0.666 / 1.333 = 0.5
        let score = rouge_l(reference, candidate);
        assert!((score - 0.5).abs() < 0.001, "got {score}");
    }

    #[test]
    fn reversal() {
        let reference = &["a", "b", "c", "d"];
        let candidate = &["d", "c", "b", "a"];
        // LCS of reversal = 1 (any single element matches)
        // R = 1/4, P = 1/4, F = 2*(0.25*0.25)/(0.25+0.25) = 0.25
        let score = rouge_l(reference, candidate);
        assert!((score - 0.25).abs() < 0.001, "got {score}");
    }

    #[test]
    fn shuffle() {
        let reference = &["the", "quick", "brown", "fox"];
        let candidate = &["brown", "the", "fox", "quick"];
        // LCS: "the" then "fox" = 2, or "brown" "fox" = 2
        // R = 2/4 = 0.5, P = 2/4 = 0.5, F = 0.5
        let score = rouge_l(reference, candidate);
        assert!((score - 0.5).abs() < 0.001, "got {score}");
    }

    #[test]
    fn insertion() {
        let reference = &["a", "b", "c"];
        let candidate = &["a", "x", "b", "y", "c"];
        // LCS = 3, R = 3/3 = 1.0, P = 3/5 = 0.6
        // F = 2 * 1.0 * 0.6 / 1.6 = 0.75
        let score = rouge_l(reference, candidate);
        assert!((score - 0.75).abs() < 0.001, "got {score}");
    }

    #[test]
    fn deletion() {
        let reference = &["a", "x", "b", "y", "c"];
        let candidate = &["a", "b", "c"];
        // LCS = 3, R = 3/5 = 0.6, P = 3/3 = 1.0
        // F = 2 * 0.6 * 1.0 / 1.6 = 0.75
        let score = rouge_l(reference, candidate);
        assert!((score - 0.75).abs() < 0.001, "got {score}");
    }

    #[test]
    fn repetition() {
        let reference = &["a", "a", "a", "b"];
        let candidate = &["a", "b", "a", "a"];
        // LCS: "a" "a" "a" can match 2 (a,b vs a,b,a,a → LCS is "a","b" = 2?
        // Actually: ref=[a,a,a,b] cand=[a,b,a,a]
        // LCS: a,b matches → 2, or a,a,a → checking: a(0) matches a(0),
        // then a(1) matches a(2), then a(2) matches a(3), giving LCS=3
        // or a(0),b(3) matches a(0),b(1) giving 2
        // Best: a,a,a = 3 from ref[0,1,2] matching cand[0,2,3]
        // R = 3/4, P = 3/4, F = 0.75
        let score = rouge_l(reference, candidate);
        assert!((score - 0.75).abs() < 0.001, "got {score}");
    }

    #[test]
    fn multilingual_cjk() {
        let reference = &["你好", "世界", "测试"];
        let candidate = &["你好", "测试"];
        // LCS = 2, R = 2/3, P = 2/2 = 1.0
        // F = 2 * (2/3) * 1.0 / (2/3 + 1.0) = (4/3) / (5/3) = 4/5 = 0.8
        let score = rouge_l(reference, candidate);
        assert!((score - 0.8).abs() < 0.001, "got {score}");
    }

    #[test]
    fn emoji_tokens() {
        let reference = &["🚀", "🎉", "✨", "🔥"];
        let candidate = &["🚀", "✨", "🔥"];
        // LCS = 3, R = 3/4 = 0.75, P = 3/3 = 1.0
        // F = 2 * 0.75 * 1.0 / 1.75 = 1.5/1.75 ≈ 0.857
        let score = rouge_l(reference, candidate);
        assert!((score - 0.857).abs() < 0.01, "got {score}");
    }

    #[test]
    fn perfect_anagram_is_not_one() {
        // An anagram should NOT score 1.0 (sanity check)
        let reference = &["listen"];
        let candidate = &["silent"];
        let score = rouge_l(reference, candidate);
        assert!(score < 1.0, "anagram should not be 1.0, got {score}");
    }

    #[test]
    fn self_rouge_is_one() {
        let tokens = &["hello", "beautiful", "world"];
        assert_eq!(rouge_l(tokens, tokens), 1.0);
    }

    #[test]
    fn superstring_at_least_half() {
        let reference = &["a", "b"];
        let candidate = &["x", "a", "y", "b", "z"];
        // LCS = 2, R = 2/2 = 1.0, P = 2/5 = 0.4
        // F = 2*1.0*0.4/1.4 = 0.571
        let score = rouge_l(reference, candidate);
        assert!(score >= 0.5, "superstring should be >= 0.5, got {score}");
    }

    #[test]
    fn rouge_l_str_basic() {
        let score = rouge_l_str("the cat sat on the mat", "the cat sat on the mat");
        assert_eq!(score, 1.0);
    }

    #[test]
    fn rouge_l_str_partial() {
        let score = rouge_l_str("the cat sat", "the dog sat");
        // LCS = "the" "sat" = 2, R = 2/3, P = 2/3
        // F = 2*(2/3)*(2/3) / (4/3) = (8/9)/(4/3) = 2/3 ≈ 0.667
        assert!((score - 0.667).abs() < 0.01, "got {score}");
    }
}
