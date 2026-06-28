//! ANSI escape code and terminal decoration removal.
//!
//! Zero-allocation where possible: scans bytes and only allocates if
//! ANSI sequences are actually found in the input.

use std::borrow::Cow;

/// Strip all ANSI escape codes from text.
///
/// Returns `Cow::Borrowed` if no ANSI sequences are found (zero-alloc fast path).
pub fn strip_ansi(input: &str) -> Cow<'_, str> {
    // Fast path: no escape character present
    if !input.contains('\x1b') {
        return Cow::Borrowed(input);
    }

    let bytes = input.as_bytes();
    let mut output = Vec::with_capacity(bytes.len());
    let mut i = 0;

    while i < bytes.len() {
        if bytes[i] == 0x1b {
            i += 1;
            if i >= bytes.len() {
                break;
            }

            match bytes[i] {
                // CSI sequence: ESC [ ... final_byte
                b'[' => {
                    i += 1;
                    // Skip parameter bytes (0x30-0x3F) and intermediate bytes (0x20-0x2F)
                    while i < bytes.len() && (0x20..=0x3F).contains(&bytes[i]) {
                        i += 1;
                    }
                    // Skip final byte (0x40-0x7E)
                    if i < bytes.len() && (0x40..=0x7E).contains(&bytes[i]) {
                        i += 1;
                    }
                }
                // OSC sequence: ESC ] ... (ST or BEL)
                b']' => {
                    i += 1;
                    while i < bytes.len() {
                        if bytes[i] == 0x07 {
                            // BEL terminator
                            i += 1;
                            break;
                        }
                        if bytes[i] == 0x1b && i + 1 < bytes.len() && bytes[i + 1] == b'\\' {
                            // ST terminator (ESC \)
                            i += 2;
                            break;
                        }
                        i += 1;
                    }
                }
                // Two-character escape sequences (ESC + single char)
                b'(' | b')' | b'*' | b'+' | b'-' | b'.' | b'/' => {
                    i += 1;
                    // Skip one more character (charset designation)
                    if i < bytes.len() {
                        i += 1;
                    }
                }
                // Single-character commands
                _ => {
                    i += 1;
                }
            }
        } else {
            output.push(bytes[i]);
            i += 1;
        }
    }

    // Safety: we only skipped escape sequences and kept valid UTF-8 bytes
    Cow::Owned(String::from_utf8(output).unwrap_or_else(|e| {
        String::from_utf8_lossy(e.as_bytes()).into_owned()
    }))
}

/// Collapse carriage-return overwrites to the final visible segment.
///
/// When terminal output uses `\r` to overwrite lines (spinners, progress),
/// this keeps only what the user would actually see.
pub fn strip_spinners(input: &str) -> Cow<'_, str> {
    if !input.contains('\r') {
        return Cow::Borrowed(input);
    }

    let mut output = String::with_capacity(input.len());
    for line in input.split('\n') {
        if line.contains('\r') {
            // Keep only the last \r segment
            if let Some(last) = line.rsplit('\r').next() {
                output.push_str(last);
            }
        } else {
            output.push_str(line);
        }
        output.push('\n');
    }

    // Remove trailing newline if input didn't end with one
    if !input.ends_with('\n') && output.ends_with('\n') {
        output.pop();
    }

    Cow::Owned(output)
}

/// Strip both ANSI codes and spinner sequences in one pass.
pub fn strip_all(input: &str) -> Cow<'_, str> {
    let no_ansi = strip_ansi(input);
    let no_spinners = strip_spinners(&no_ansi);

    match (no_ansi, no_spinners) {
        (Cow::Borrowed(_), Cow::Borrowed(_)) => Cow::Borrowed(input),
        (_, owned) => owned,
    }
}

/// Statistics from ANSI stripping.
#[derive(Debug, Clone, Default)]
pub struct AnsiRemoverStats {
    /// Number of bytes removed.
    pub bytes_removed: usize,
    /// Number of ANSI sequences found.
    pub sequences_found: usize,
    /// Number of spinner lines collapsed.
    pub spinners_collapsed: usize,
}

/// Strip ANSI with statistics tracking.
pub fn strip_ansi_with_stats(input: &str) -> (Cow<'_, str>, AnsiRemoverStats) {
    let mut stats = AnsiRemoverStats::default();

    if !input.contains('\x1b') && !input.contains('\r') {
        return (Cow::Borrowed(input), stats);
    }

    let result = strip_all(input);
    if let Cow::Owned(ref s) = result {
        stats.bytes_removed = input.len().saturating_sub(s.len());
        // Count escape sequences
        stats.sequences_found = input.matches('\x1b').count();
        // Count spinner lines
        stats.spinners_collapsed = input.lines().filter(|l| l.contains('\r')).count();
    }

    (result, stats)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_no_ansi_passthrough() {
        let input = "hello world";
        let result = strip_ansi(input);
        assert!(matches!(result, Cow::Borrowed(_)));
        assert_eq!(result, "hello world");
    }

    #[test]
    fn test_strip_colors() {
        let input = "\x1b[31mred\x1b[0m normal \x1b[1;32mgreen\x1b[0m";
        let result = strip_ansi(input);
        assert_eq!(result, "red normal green");
    }

    #[test]
    fn test_strip_cursor_movement() {
        let input = "\x1b[2J\x1b[Hcontent\x1b[10Amore";
        let result = strip_ansi(input);
        assert_eq!(result, "contentmore");
    }

    #[test]
    fn test_strip_osc() {
        let input = "\x1b]0;window title\x07content";
        let result = strip_ansi(input);
        assert_eq!(result, "content");
    }

    #[test]
    fn test_strip_spinners() {
        let input = "loading...\rloading...\rdone!";
        let result = strip_spinners(input);
        assert_eq!(result, "done!");
    }

    #[test]
    fn test_multiline_spinners() {
        let input = "line1\nspinner\rresult\nline3";
        let result = strip_spinners(input);
        assert_eq!(result, "line1\nresult\nline3");
    }

    #[test]
    fn test_strip_all() {
        let input = "\x1b[33mloading\x1b[0m\rDone!";
        let result = strip_all(input);
        assert_eq!(result, "Done!");
    }

    #[test]
    fn test_stats() {
        let input = "\x1b[31mred\x1b[0m\nspinner\rdone";
        let (result, stats) = strip_ansi_with_stats(input);
        assert_eq!(result, "red\ndone");
        assert!(stats.bytes_removed > 0);
        assert_eq!(stats.sequences_found, 2);
        assert_eq!(stats.spinners_collapsed, 1);
    }
}
