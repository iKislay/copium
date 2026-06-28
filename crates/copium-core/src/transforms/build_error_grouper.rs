//! Build error grouping and compiler output normalization.
//!
//! Groups identical build errors across multiple files and normalizes
//! compiler output for better compression. Companion to the Python
//! `_group_build_errors`, `_compress_docker_build`, and
//! `_normalize_compiler_errors` functions in `error_compressor.py`.

use std::borrow::Cow;
use std::collections::HashMap;

use regex::Regex;

/// Group identical build errors across files.
///
/// Instead of repeating the same error N times, produces a single
/// line with a file count.
///
/// # Example
///
/// ```
/// use copium_core::transforms::build_error_grouper::group_build_errors;
///
/// let input = "src/a.ts: error TS2322: Type mismatch\n\
///              src/b.ts: error TS2322: Type mismatch\n\
///              src/c.ts: error TS2322: Type mismatch\n";
///
/// let result = group_build_errors(input);
/// assert!(result.contains("3 files"));
/// ```
pub fn group_build_errors(input: &str) -> Cow<'_, str> {
    lazy_static! {
        // TypeScript: src/a.ts: error TS2322: ...
        static ref TS_ERROR: Regex =
            Regex::new(r"(?m)^(.+?):\s*(error TS\d+:\s*.+)$").unwrap();
        // Rust: src/main.rs: error[E0308]: ...
        static ref RUST_ERROR: Regex =
            Regex::new(r"(?m)^(.+?):\s*(error\[E\d+\]:\s*.+)$").unwrap();
        // GCC/Clang: file.c:10:5: error: ...
        static ref GCC_ERROR: Regex =
            Regex::new(r"(?m)^(.+?:\d+:\d+):\s*(error:\s*.+)$").unwrap();
    }

    let patterns: &[&Regex] = &[&TS_ERROR, &RUST_ERROR, &GCC_ERROR];

    for pattern in patterns {
        let captures: Vec<_> = pattern.captures_iter(input).collect();
        if captures.len() < 2 {
            continue;
        }

        let mut groups: HashMap<String, Vec<String>> = HashMap::new();
        for cap in &captures {
            let file = cap[1].trim().to_string();
            let msg = cap[2].trim().to_string();
            groups.entry(msg).or_default().push(file);
        }

        let mut result = input.to_string();
        let mut changed = false;

        for (msg, files) in &groups {
            if files.len() < 2 {
                continue;
            }
            changed = true;

            // Remove individual lines
            for file in files {
                let escaped_file = regex::escape(file);
                let escaped_msg = regex::escape(msg);
                let line_re =
                    Regex::new(&format!(r"(?m)^{escaped_file}:\s*{escaped_msg}\s*$\n?")).unwrap();
                result = line_re.replace_all(&result, "").to_string();
            }

            // Add grouped line
            let file_list: String = if files.len() <= 5 {
                files.join(", ")
            } else {
                format!(
                    "{}, ... +{} more",
                    files[..5].join(", "),
                    files.len() - 5
                )
            };
            result = format!(
                "{}\n{} ({} files: {})",
                result.trim_end(),
                msg,
                files.len(),
                file_list
            );
        }

        if changed {
            return Cow::Owned(result);
        }
    }

    Cow::Borrowed(input)
}

/// Normalize absolute paths in compiler output to relative paths.
pub fn normalize_paths(input: &str) -> Cow<'_, str> {
    lazy_static! {
        static ref ABS_PATH: Regex =
            Regex::new(r"(?:/home/\w+/[\w.\-]+/|/Users/\w+/[\w.\-]+/|/workspace/[\w.\-]+/)")
                .unwrap();
    }

    if ABS_PATH.is_match(input) {
        Cow::Owned(ABS_PATH.replace_all(input, "").to_string())
    } else {
        Cow::Borrowed(input)
    }
}

/// Remove timestamps from compiler output.
pub fn strip_timestamps(input: &str) -> Cow<'_, str> {
    lazy_static! {
        static ref ISO_TS: Regex =
            Regex::new(r"\[\d{4}-\d{2}-\d{2}T[\d:.]+Z?\]\s*").unwrap();
        static ref TIME_TS: Regex = Regex::new(r"\[\d{2}:\d{2}:\d{2}\]\s*").unwrap();
    }

    let result = ISO_TS.replace_all(input, "");
    if result != input {
        let result2 = TIME_TS.replace_all(&result, "");
        return Cow::Owned(result2.to_string());
    }

    if TIME_TS.is_match(input) {
        Cow::Owned(TIME_TS.replace_all(input, "").to_string())
    } else {
        Cow::Borrowed(input)
    }
}

/// Compress Docker build output by removing download/progress lines.
pub fn compress_docker_build(input: &str) -> Cow<'_, str> {
    lazy_static! {
        static ref DOWNLOAD: Regex = Regex::new(
            r"(?mi)^(?:Downloading|Extracting|Pulling fs layer|Waiting|Download complete|Pull complete|Verifying Checksum|Already exists)\s*.*$"
        ).unwrap();
        static ref PROGRESS: Regex = Regex::new(
            r"(?m)^.*?(?:\d+\.\d+\s*[kMG]B/\d+\.\d+\s*[kMG]B|[\d.]+%|\[={>}\s*\]).*$"
        ).unwrap();
    }

    if !DOWNLOAD.is_match(input) && !PROGRESS.is_match(input) {
        return Cow::Borrowed(input);
    }

    let mut removed = 0usize;
    let mut lines: Vec<&str> = Vec::new();

    for line in input.lines() {
        if DOWNLOAD.is_match(line) || PROGRESS.is_match(line) {
            removed += 1;
            continue;
        }
        lines.push(line);
    }

    if removed > 0 {
        lines.push(&format!("  ({removed} download/progress lines removed)"));
        // We can't return a reference to a local, so build the string
        let mut result = lines[..lines.len() - 1].join("\n");
        result.push_str(&format!("\n  ({removed} download/progress lines removed)"));
        Cow::Owned(result)
    } else {
        Cow::Borrowed(input)
    }
}

#[macro_use]
extern crate lazy_static;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_group_ts_errors() {
        let input = "src/a.ts: error TS2322: Type mismatch\n\
                     src/b.ts: error TS2322: Type mismatch\n";
        let result = group_build_errors(input);
        assert!(result.contains("2 files"));
    }

    #[test]
    fn test_normalize_paths() {
        let input = "/home/user/project/src/file.ts:10: error";
        let result = normalize_paths(input);
        assert!(!result.contains("/home/user/project/"));
        assert!(result.contains("src/file.ts"));
    }

    #[test]
    fn test_strip_timestamps() {
        let input = "[2026-06-28T10:30:00Z] error: failed";
        let result = strip_timestamps(input);
        assert!(!result.contains("2026"));
        assert!(result.contains("error: failed"));
    }

    #[test]
    fn test_no_change_passthrough() {
        let input = "normal text without errors";
        let result = group_build_errors(input);
        assert!(matches!(result, Cow::Borrowed(_)));
    }
}
