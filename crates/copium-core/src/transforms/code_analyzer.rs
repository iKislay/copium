//! Code analyzer — language-agnostic and language-specific rules for
//! reducing bloat in source code without losing semantic content.
//!
//! Rules operate via pure byte scanning (no regex, no language deps).
//! Language-specific rules are opt-in and guarded by content type.

/// Result of applying code analysis rules to a text block.
#[derive(Debug, Clone)]
pub struct AnalysisResult {
    pub output: String,
    pub lines_removed: usize,
    pub rules_applied: Vec<&'static str>,
}

/// Detected programming language for language-specific rules.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    Python,
    JavaScript,
    TypeScript,
    Go,
    Rust,
    Unknown,
}

impl Language {
    pub fn from_hint(hint: &str) -> Self {
        match hint.to_lowercase().as_str() {
            "python" | "py" => Self::Python,
            "javascript" | "js" => Self::JavaScript,
            "typescript" | "ts" => Self::TypeScript,
            "go" | "golang" => Self::Go,
            "rust" | "rs" => Self::Rust,
            _ => Self::Unknown,
        }
    }
}

/// Apply all language-agnostic rules to the input.
pub fn analyze_generic(input: &str) -> AnalysisResult {
    let mut output = input.to_string();
    let mut total_removed = 0;
    let mut rules = Vec::new();

    let before = output.lines().count();
    output = collapse_redundant_blank_lines(&output);
    let after = output.lines().count();
    if after < before {
        total_removed += before - after;
        rules.push("redundant_blank_lines");
    }

    let before = output.len();
    output = strip_trailing_whitespace(&output);
    if output.len() < before {
        rules.push("trailing_whitespace");
    }

    let before = output.lines().count();
    output = collapse_repeated_lines(&output);
    let after = output.lines().count();
    if after < before {
        total_removed += before - after;
        rules.push("repeated_line_collapsing");
    }

    let before = output.lines().count();
    output = collapse_commented_code_blocks(&output);
    let after = output.lines().count();
    if after < before {
        total_removed += before - after;
        rules.push("commented_code_blocks");
    }

    AnalysisResult {
        output,
        lines_removed: total_removed,
        rules_applied: rules,
    }
}

/// Apply language-specific rules on top of generic analysis.
pub fn analyze(input: &str, language: Language) -> AnalysisResult {
    let mut result = analyze_generic(input);

    match language {
        Language::Python => {
            let before = result.output.lines().count();
            result.output = python_rules(&result.output);
            let after = result.output.lines().count();
            if after < before {
                result.lines_removed += before - after;
                result.rules_applied.push("python_docstring_collapse");
            }
        }
        Language::JavaScript | Language::TypeScript => {
            let before = result.output.lines().count();
            result.output = js_ts_rules(&result.output);
            let after = result.output.lines().count();
            if after < before {
                result.lines_removed += before - after;
                result.rules_applied.push("js_ts_console_collapse");
            }
        }
        Language::Go => {
            let before = result.output.lines().count();
            result.output = go_rules(&result.output);
            let after = result.output.lines().count();
            if after < before {
                result.lines_removed += before - after;
                result.rules_applied.push("go_error_check_collapse");
            }
        }
        Language::Rust => {
            let before = result.output.lines().count();
            result.output = rust_rules(&result.output);
            let after = result.output.lines().count();
            if after < before {
                result.lines_removed += before - after;
                result.rules_applied.push("rust_derive_collapse");
            }
        }
        Language::Unknown => {}
    }

    result
}

/// Collapse 3+ consecutive blank lines into a single blank line.
fn collapse_redundant_blank_lines(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut consecutive_blanks = 0;

    for line in input.lines() {
        if line.trim().is_empty() {
            consecutive_blanks += 1;
        } else {
            if consecutive_blanks >= 3 {
                // Collapse to one preserved blank line + separator
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push('\n');
            } else if consecutive_blanks > 0 {
                // Keep 1-2 blank lines as-is + separator
                if !result.is_empty() {
                    result.push('\n');
                }
                for _ in 0..consecutive_blanks {
                    result.push('\n');
                }
            } else if !result.is_empty() {
                result.push('\n');
            }
            consecutive_blanks = 0;
            result.push_str(line);
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Strip trailing whitespace from each line.
fn strip_trailing_whitespace(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let mut result = String::with_capacity(input.len());

    for (i, line) in lines.iter().enumerate() {
        result.push_str(line.trim_end());
        if i < lines.len() - 1 {
            result.push('\n');
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Collapse N consecutive identical lines (N >= 3) into a single line
/// with a "(xN)" annotation.
fn collapse_repeated_lines(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    if lines.len() < 3 {
        return input.to_string();
    }

    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        let current = lines[i];
        let mut count = 1;
        while i + count < lines.len() && lines[i + count] == current {
            count += 1;
        }

        if count >= 3 {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(current);
            result.push_str(&format!(" (x{count})"));
            i += count;
        } else {
            for line in &lines[i..i + count] {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(line);
            }
            i += count;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Collapse 3+ consecutive commented lines into a summary.
fn collapse_commented_code_blocks(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    if lines.len() < 3 {
        return input.to_string();
    }

    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        if is_comment_line(lines[i]) {
            let start = i;
            while i < lines.len() && is_comment_line(lines[i]) {
                i += 1;
            }
            let count = i - start;
            if count >= 3 {
                if !result.is_empty() {
                    result.push('\n');
                }
                let prefix = detect_comment_prefix(lines[start]);
                result.push_str(&format!("{prefix} [{count} lines of commented code]"));
            } else {
                for line in &lines[start..i] {
                    if !result.is_empty() {
                        result.push('\n');
                    }
                    result.push_str(line);
                }
            }
        } else {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(lines[i]);
            i += 1;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Check if a line is a comment (starts with # or //).
/// Excludes Rust-style attributes (#[...]) and shebangs (#!).
fn is_comment_line(line: &str) -> bool {
    let trimmed = line.trim();
    if trimmed.starts_with("#!") {
        return false;
    }
    if trimmed.starts_with("#[") {
        return false;
    }
    trimmed.starts_with('#')
        || trimmed.starts_with("//")
        || trimmed.starts_with("/*")
        || trimmed.starts_with('*')
}

/// Detect the comment prefix used.
fn detect_comment_prefix(line: &str) -> &'static str {
    let trimmed = line.trim();
    if trimmed.starts_with("//") {
        "//"
    } else if trimmed.starts_with('#') {
        "#"
    } else {
        "//"
    }
}

// ── Language-specific rules ────────────────────────────────────────

/// Python: collapse consecutive pass-only or docstring-heavy blocks.
fn python_rules(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        let trimmed = lines[i].trim();
        // Collapse consecutive `pass` statements (3+)
        if trimmed == "pass" {
            let start = i;
            while i < lines.len() && lines[i].trim() == "pass" {
                i += 1;
            }
            let count = i - start;
            if count >= 3 {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(&format!("    pass (x{count})"));
            } else {
                for line in &lines[start..i] {
                    if !result.is_empty() {
                        result.push('\n');
                    }
                    result.push_str(line);
                }
            }
        } else {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(lines[i]);
            i += 1;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// JS/TS: collapse consecutive console.log / console.debug calls (3+).
fn js_ts_rules(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        let trimmed = lines[i].trim();
        if trimmed.starts_with("console.log") || trimmed.starts_with("console.debug") {
            let start = i;
            while i < lines.len() {
                let t = lines[i].trim();
                if t.starts_with("console.log") || t.starts_with("console.debug") {
                    i += 1;
                } else {
                    break;
                }
            }
            let count = i - start;
            if count >= 3 {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(&format!("  // [{count} console statements]"));
            } else {
                for line in &lines[start..i] {
                    if !result.is_empty() {
                        result.push('\n');
                    }
                    result.push_str(line);
                }
            }
        } else {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(lines[i]);
            i += 1;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Go: collapse consecutive `if err != nil { return err }` patterns (3+).
fn go_rules(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        let trimmed = lines[i].trim();
        if trimmed.starts_with("if err != nil") {
            // Count consecutive error check blocks (3 lines each: if, return, })
            let mut block_count = 0;
            let mut j = i;
            while j < lines.len() && lines[j].trim().starts_with("if err != nil") {
                // Expect: if err != nil {, return ..., }
                if j + 2 < lines.len()
                    && lines[j + 1].trim().starts_with("return")
                    && lines[j + 2].trim() == "}"
                {
                    block_count += 1;
                    j += 3;
                } else {
                    break;
                }
            }
            if block_count >= 3 {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(&format!("\t// [{block_count} error check blocks]"));
                i = j;
            } else {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(lines[i]);
                i += 1;
            }
        } else {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(lines[i]);
            i += 1;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Rust: collapse consecutive #[derive(...)] attributes (3+) into summary.
fn rust_rules(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let mut result = String::with_capacity(input.len());
    let mut i = 0;

    while i < lines.len() {
        let trimmed = lines[i].trim();
        if trimmed.starts_with("#[derive(") || trimmed.starts_with("#[cfg(") {
            let start = i;
            while i < lines.len() {
                let t = lines[i].trim();
                if t.starts_with("#[") {
                    i += 1;
                } else {
                    break;
                }
            }
            let count = i - start;
            if count >= 3 {
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(&format!("// [{count} attribute annotations]"));
            } else {
                for line in &lines[start..i] {
                    if !result.is_empty() {
                        result.push('\n');
                    }
                    result.push_str(line);
                }
            }
        } else {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str(lines[i]);
            i += 1;
        }
    }

    if input.ends_with('\n') && !result.ends_with('\n') {
        result.push('\n');
    }

    result
}

/// Estimate how much bloat a code block has (0.0–1.0).
/// Counts blank lines, commented lines, and repeated lines.
pub fn estimate_bloat(input: &str) -> f32 {
    let lines: Vec<&str> = input.lines().collect();
    if lines.is_empty() {
        return 0.0;
    }

    let total = lines.len();
    let mut bloat_lines = 0;

    let mut consecutive_blanks = 0;
    let mut prev_line: Option<&str> = None;
    let mut repeat_count = 0;

    for line in &lines {
        let trimmed = line.trim();

        // Count excess blank lines (3+ consecutive)
        if trimmed.is_empty() {
            consecutive_blanks += 1;
            if consecutive_blanks >= 3 {
                bloat_lines += 1;
            }
        } else {
            consecutive_blanks = 0;
        }

        // Count commented lines
        if is_comment_line(line) && !trimmed.is_empty() {
            bloat_lines += 1;
        }
        // Count repeated lines (non-comment only to avoid double-counting)
        else if let Some(prev) = prev_line {
            if *line == prev {
                repeat_count += 1;
                if repeat_count >= 2 {
                    bloat_lines += 1;
                }
            } else {
                repeat_count = 0;
            }
        }
        prev_line = Some(line);
    }

    (bloat_lines as f32 / total as f32).min(1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generic_collapses_blank_lines() {
        let input = "a\n\n\n\n\nb\n";
        let result = analyze_generic(input);
        assert!(result.output.contains('a'));
        assert!(result.output.contains('b'));
        assert!(result.rules_applied.contains(&"redundant_blank_lines"));
        // Should have at most 1 blank line between a and b
        let blank_runs: Vec<&str> = result.output.split("a\n").collect();
        assert!(!blank_runs[1].starts_with("\n\n\n"));
    }

    #[test]
    fn generic_strips_trailing_whitespace() {
        let input = "hello   \nworld  \n";
        let result = analyze_generic(input);
        for line in result.output.lines() {
            assert_eq!(line, line.trim_end());
        }
    }

    #[test]
    fn generic_collapses_repeated_lines() {
        let input = "log line\nlog line\nlog line\nlog line\nother\n";
        let result = analyze_generic(input);
        assert!(result.output.contains("(x4)"));
        assert!(result.rules_applied.contains(&"repeated_line_collapsing"));
    }

    #[test]
    fn generic_collapses_comments() {
        let input = "code\n# comment 1\n# comment 2\n# comment 3\n# comment 4\nmore code\n";
        let result = analyze_generic(input);
        assert!(result.output.contains("[4 lines of commented code]"));
    }

    #[test]
    fn generic_preserves_short_comments() {
        let input = "code\n# comment 1\n# comment 2\nmore code\n";
        let result = analyze_generic(input);
        assert!(result.output.contains("# comment 1"));
        assert!(result.output.contains("# comment 2"));
    }

    #[test]
    fn python_collapses_pass_statements() {
        let input = "def a():\n    pass\n    pass\n    pass\n    pass\n";
        let result = analyze(input, Language::Python);
        assert!(result.output.contains("pass (x4)"));
    }

    #[test]
    fn js_collapses_console_logs() {
        let input = "function f() {\n  console.log('a')\n  console.log('b')\n  console.log('c')\n  return x;\n}\n";
        let result = analyze(input, Language::JavaScript);
        assert!(result.output.contains("[3 console statements]"));
    }

    #[test]
    fn go_collapses_error_checks() {
        let input = "if err != nil {\n\treturn err\n}\nif err != nil {\n\treturn err\n}\nif err != nil {\n\treturn err\n}\n";
        let result = analyze(input, Language::Go);
        assert!(result.output.contains("[3 error check blocks]"));
    }

    #[test]
    fn rust_collapses_derives() {
        let input =
            "#[derive(Debug)]\n#[derive(Clone)]\n#[derive(PartialEq)]\n#[cfg(test)]\nstruct Foo;\n";
        let result = analyze(input, Language::Rust);
        assert!(result.output.contains("[4 attribute annotations]"));
    }

    #[test]
    fn shebang_preserved() {
        let input = "#!/usr/bin/env python3\n# comment\n# comment\n# comment\ncode\n";
        let result = analyze_generic(input);
        assert!(
            result.output.starts_with("#!/usr/bin/env python3"),
            "shebang must be preserved, got: {}",
            result.output
        );
    }

    #[test]
    fn estimate_bloat_empty() {
        assert_eq!(estimate_bloat(""), 0.0);
    }

    #[test]
    fn estimate_bloat_clean_code() {
        let input = "fn main() {\n    println!(\"hello\");\n}\n";
        let bloat = estimate_bloat(input);
        assert!(bloat < 0.3, "clean code should have low bloat: {bloat}");
    }

    #[test]
    fn estimate_bloat_heavy_comments() {
        let input = "// a\n// b\n// c\n// d\n// e\ncode\n";
        let bloat = estimate_bloat(input);
        assert!(
            bloat > 0.5,
            "heavily commented code should have high bloat: {bloat}"
        );
    }
}
