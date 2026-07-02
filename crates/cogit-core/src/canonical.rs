//! Canonical JSON profile (ADR-0010, docs/spec/object-format-v1.md):
//! UTF-8, keys sorted by code point, minimal escaping, integers only with
//! |n| <= 2^53 - 1, floats forbidden, no insignificant whitespace.
//!
//! serde_json without `preserve_order` serializes maps via BTreeMap
//! (code-point key order) and escapes exactly like the profile demands
//! (\b \t \n \f \r, lowercase \u00xx for other controls, raw UTF-8 for
//! non-ASCII), so canonicalization is validation + plain `to_string`.

use serde_json::Value;

use crate::error::{CoreError, Result};

pub const MAX_SAFE_INT: u64 = (1 << 53) - 1;

fn validate_value(value: &Value, path: &str) -> Result<()> {
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(n) => {
            if n.is_f64() {
                return Err(CoreError::User(format!(
                    "canonical json: float forbidden at {path}"
                )));
            }
            let in_range = if let Some(i) = n.as_i64() {
                i.unsigned_abs() <= MAX_SAFE_INT
            } else if let Some(u) = n.as_u64() {
                u <= MAX_SAFE_INT
            } else {
                false
            };
            if !in_range {
                return Err(CoreError::User(format!(
                    "canonical json: integer out of safe range at {path}"
                )));
            }
            Ok(())
        }
        Value::Array(items) => {
            for (i, item) in items.iter().enumerate() {
                validate_value(item, &format!("{path}[{i}]"))?;
            }
            Ok(())
        }
        Value::Object(map) => {
            for (key, item) in map {
                validate_value(item, &format!("{path}.{key}"))?;
            }
            Ok(())
        }
    }
}

/// Canonical JSON text for a JSON-compatible value.
pub fn canonical_json(value: &Value) -> Result<String> {
    validate_value(value, "$")?;
    serde_json::to_string(value).map_err(|e| CoreError::User(format!("canonical json: {e}")))
}

pub fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>> {
    Ok(canonical_json(value)?.into_bytes())
}

/// Parse JSON while rejecting floats at the boundary.
pub fn parse_json(text: &str) -> Result<Value> {
    let value: Value = serde_json::from_str(text)
        .map_err(|e| CoreError::User(format!("invalid json: {e}")))?;
    validate_value(&value, "$")?;
    Ok(value)
}
