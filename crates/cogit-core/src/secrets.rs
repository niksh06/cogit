//! Suspected-secret rejection (ADR-0009, invariant 21; v2 per COG-023).
//! Reject the write, never redact-and-store. Port of prototype/cogit/secrets.py.

use regex::Regex;
use serde_json::Value;
use std::sync::OnceLock;

use crate::error::{CoreError, Result};

const ENTROPY_THRESHOLD: f64 = 4.2; // bits/char: hex below, random base64 above

fn patterns() -> &'static Vec<(&'static str, Regex)> {
    static PATTERNS: OnceLock<Vec<(&'static str, Regex)>> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        vec![
            ("aws access key id", Regex::new(r"\bAKIA[0-9A-Z]{16}\b").unwrap()),
            (
                "aws secret access key",
                Regex::new(r#"(?i)\baws_?secret[^\n]{0,20}[=:]\s*['"]?[A-Za-z0-9/+=]{40}\b"#).unwrap(),
            ),
            ("private key block", Regex::new(r"-----BEGIN [A-Z ]*PRIVATE KEY-----").unwrap()),
            ("github token", Regex::new(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b").unwrap()),
            ("slack token", Regex::new(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b").unwrap()),
            ("openai-style key", Regex::new(r"\bsk-[A-Za-z0-9_-]{20,}\b").unwrap()),
            ("anthropic key", Regex::new(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b").unwrap()),
            (
                "jwt",
                Regex::new(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b").unwrap(),
            ),
            (
                "credential assignment",
                Regex::new(r"(?i)\b(password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*\S{8,}").unwrap(),
            ),
            (
                "credentials in url",
                Regex::new(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{4,}@").unwrap(),
            ),
        ]
    })
}

fn token_re() -> &'static Regex {
    static TOKEN: OnceLock<Regex> = OnceLock::new();
    TOKEN.get_or_init(|| Regex::new(r"[A-Za-z0-9+/_=-]{24,}").unwrap())
}

fn shannon_entropy(text: &str) -> f64 {
    let mut counts = std::collections::HashMap::new();
    for ch in text.chars() {
        *counts.entry(ch).or_insert(0usize) += 1;
    }
    let total = text.chars().count() as f64;
    -counts
        .values()
        .map(|&n| {
            let p = n as f64 / total;
            p * p.log2()
        })
        .sum::<f64>()
}

/// Filesystem-path guard (COG-048): several word-like segments joined by
/// '/'. Random base64 also contains '/', so segments must individually
/// read as words/dates (at most a leading capital), not random chunks.
fn looks_like_path(token: &str) -> bool {
    if token.matches('/').count() < 2 {
        return false;
    }
    let segments: Vec<&str> = token.split('/').filter(|s| !s.is_empty()).collect();
    if segments.len() < 2 {
        return false;
    }
    let wordy = segments
        .iter()
        .filter(|segment| {
            let mut chars = segment.chars();
            chars.next().map(|c| c.is_ascii_alphanumeric()).unwrap_or(false)
                && chars.all(|c| {
                    c.is_ascii_lowercase() || c.is_ascii_digit() || "._+-".contains(c)
                })
        })
        .count();
    wordy * 3 >= segments.len() * 2
}

fn looks_like_random_token(token: &str) -> bool {
    if token.bytes().all(|b| b.is_ascii_hexdigit()) {
        return false; // covers Cogit object ids and other hashes
    }
    if looks_like_path(token) {
        return false; // report/artifact paths are legitimate belief values
    }
    let has_upper = token.chars().any(|c| c.is_ascii_uppercase());
    let has_lower = token.chars().any(|c| c.is_ascii_lowercase());
    let has_digit = token.chars().any(|c| c.is_ascii_digit());
    if !(has_upper && has_lower && has_digit) {
        return false;
    }
    shannon_entropy(token) >= ENTROPY_THRESHOLD
}

fn scan_text(text: &str, where_: &str) -> Result<()> {
    for (label, pattern) in patterns() {
        if pattern.is_match(text) {
            return Err(CoreError::User(format!(
                "{where_}: rejected — content matches suspected secret ({label}); secrets must not be stored in Cogit"
            )));
        }
    }
    for token in token_re().find_iter(text) {
        let token = token.as_str();
        if looks_like_random_token(token) {
            return Err(CoreError::User(format!(
                "{where_}: rejected — high-entropy token looks like a secret ('{}…', {} chars); secrets must not be stored in Cogit",
                &token[..8.min(token.len())],
                token.len()
            )));
        }
    }
    Ok(())
}

/// Raise a user error if any string in the value looks like a secret.
pub fn reject_suspected_secrets(value: &Value, where_: &str) -> Result<()> {
    match value {
        Value::String(s) => scan_text(s, where_),
        Value::Array(items) => items.iter().try_for_each(|v| reject_suspected_secrets(v, where_)),
        Value::Object(map) => {
            for (key, item) in map {
                scan_text(key, where_)?;
                reject_suspected_secrets(item, where_)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}
