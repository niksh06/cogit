//! Object schemas, validation, and preimage/ID computation.
//! Port of the reference validators (prototype/cogit/objects.py); unknown
//! fields are rejected.

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::canonical::canonical_json_bytes;
use crate::error::{CoreError, Result};

pub const OBJECT_TYPES: [&str; 6] = [
    "claim",
    "assertion",
    "mindset",
    "thought",
    "anchor",
    "annotation",
];

const CLAIM_KINDS: [&str; 5] = [
    "user_preference",
    "tool_observation",
    "document_claim",
    "agent_decision",
    "policy_constraint",
];
const ASSERTION_STATUSES: [&str; 3] = ["asserted", "refuted", "superseded"];
const SOURCE_TYPES: [&str; 7] = ["prompt", "tool", "file", "url", "system", "manual", "agent"];
const THOUGHT_OPERATIONS: [&str; 6] = ["commit", "merge", "checkout", "anchor", "import", "repair"];

fn user_err<T>(msg: impl Into<String>) -> Result<T> {
    Err(CoreError::User(msg.into()))
}

pub fn is_oid(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..].bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

fn is_timestamp(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.len() != 20 {
        return false;
    }
    for (i, b) in bytes.iter().enumerate() {
        let ok = match i {
            4 | 7 => *b == b'-',
            10 => *b == b'T',
            13 | 16 => *b == b':',
            19 => *b == b'Z',
            _ => b.is_ascii_digit(),
        };
        if !ok {
            return false;
        }
    }
    true
}

fn is_ref_segment(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'.' || b == b'_' || b == b'-')
}

fn check_keys(map: &Map<String, Value>, allowed: &[&str], optional: &[&str], where_: &str) -> Result<()> {
    for key in map.keys() {
        if !allowed.contains(&key.as_str()) && !optional.contains(&key.as_str()) {
            return user_err(format!("{where_}: unknown fields rejected: {key}"));
        }
    }
    Ok(())
}

fn get_str<'a>(map: &'a Map<String, Value>, field: &str, where_: &str) -> Result<&'a str> {
    match map.get(field).and_then(Value::as_str) {
        Some(s) if !s.is_empty() => Ok(s),
        _ => user_err(format!("{where_}: field '{field}' must be a non-empty string")),
    }
}

fn get_oid<'a>(map: &'a Map<String, Value>, field: &str, where_: &str) -> Result<&'a str> {
    let value = get_str(map, field, where_)?;
    if !is_oid(value) {
        return user_err(format!("{where_}: field '{field}' must be a 'sha256:<64-hex>' reference"));
    }
    Ok(value)
}

fn get_timestamp(map: &Map<String, Value>, field: &str, where_: &str) -> Result<()> {
    let value = get_str(map, field, where_)?;
    if !is_timestamp(value) {
        return user_err(format!("{where_}: field '{field}' must be ISO-8601 UTC with 'Z' suffix"));
    }
    Ok(())
}

fn get_oid_list<'a>(
    map: &'a Map<String, Value>,
    field: &str,
    require_sorted: bool,
    where_: &str,
) -> Result<Vec<&'a str>> {
    let items = match map.get(field).and_then(Value::as_array) {
        Some(items) => items,
        None => return user_err(format!("{where_}: field '{field}' must be a list")),
    };
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        match item.as_str() {
            Some(s) if is_oid(s) => out.push(s),
            _ => return user_err(format!("{where_}: field '{field}' must contain object ids")),
        }
    }
    let mut dedup = out.clone();
    dedup.sort_unstable();
    dedup.dedup();
    if dedup.len() != out.len() {
        return user_err(format!("{where_}: field '{field}' must not contain duplicates"));
    }
    if require_sorted && dedup != out {
        return user_err(format!("{where_}: field '{field}' must be sorted lexicographically"));
    }
    Ok(out)
}

fn check_flat_object<'a>(map: &'a Map<String, Value>, field: &str, where_: &str) -> Result<&'a Map<String, Value>> {
    let inner = match map.get(field).and_then(Value::as_object) {
        Some(inner) => inner,
        None => return user_err(format!("{where_}: field '{field}' must be an object")),
    };
    for (key, item) in inner {
        let scalar = matches!(item, Value::Null | Value::Bool(_) | Value::String(_))
            || matches!(item, Value::Number(n) if !n.is_f64());
        if !scalar {
            return user_err(format!("{where_}: field '{field}.{key}' must be a scalar"));
        }
    }
    Ok(inner)
}

fn validate_claim(map: &Map<String, Value>) -> Result<()> {
    check_keys(map, &["type", "kind", "subject", "predicate", "object", "qualifiers"], &["negates"], "claim")?;
    let kind = get_str(map, "kind", "claim")?;
    if !CLAIM_KINDS.contains(&kind) {
        return user_err(format!("claim: kind must be one of {CLAIM_KINDS:?}"));
    }
    get_str(map, "subject", "claim")?;
    get_str(map, "predicate", "claim")?;
    let object_ok = match map.get("object") {
        Some(Value::String(_)) | Some(Value::Bool(_)) => true,
        Some(Value::Number(n)) => !n.is_f64(),
        _ => false,
    };
    if !object_ok {
        return user_err("claim: object must be a scalar (string, integer, or boolean)");
    }
    check_flat_object(map, "qualifiers", "claim")?;
    if map.contains_key("negates") {
        get_oid(map, "negates", "claim")?;
    }
    Ok(())
}

fn validate_assertion(map: &Map<String, Value>) -> Result<()> {
    check_keys(
        map,
        &["type", "claim", "status", "source", "confidence_bps", "asserted_at", "actor", "method"],
        &["premises"],
        "assertion",
    )?;
    if map.contains_key("premises") {
        let premises = get_oid_list(map, "premises", true, "assertion")?;
        if premises.is_empty() {
            return user_err("assertion: premises must be a non-empty array of assertion ids");
        }
    }
    get_oid(map, "claim", "assertion")?;
    let status = get_str(map, "status", "assertion")?;
    if !ASSERTION_STATUSES.contains(&status) {
        return user_err(format!("assertion: status must be one of {ASSERTION_STATUSES:?}"));
    }
    let source = match map.get("source").and_then(Value::as_object) {
        Some(source) => source,
        None => return user_err("assertion: source must be an object"),
    };
    check_keys(source, &["type"], &["uri"], "assertion.source")?;
    let source_type = get_str(source, "type", "assertion.source")?;
    if !SOURCE_TYPES.contains(&source_type) {
        return user_err(format!("assertion: source.type must be one of {SOURCE_TYPES:?}"));
    }
    if source.contains_key("uri") {
        get_str(source, "uri", "assertion.source")?;
    }
    let confidence = map.get("confidence_bps").and_then(Value::as_i64);
    match confidence {
        Some(c) if (0..=10000).contains(&c) && !map["confidence_bps"].is_boolean() => {}
        _ => return user_err("assertion: confidence_bps must be an integer from 0 to 10000"),
    }
    get_timestamp(map, "asserted_at", "assertion")?;
    let actor = get_str(map, "actor", "assertion")?;
    if actor.chars().any(char::is_whitespace) {
        return user_err("assertion: actor must not contain whitespace");
    }
    let method = check_flat_object(map, "method", "assertion")?;
    match method.get("type").and_then(Value::as_str) {
        Some(t) if !t.is_empty() => Ok(()),
        _ => user_err("assertion: method.type must be a non-empty string"),
    }
}

fn validate_mindset(map: &Map<String, Value>) -> Result<()> {
    check_keys(map, &["type", "assertions", "created_at"], &[], "mindset")?;
    get_oid_list(map, "assertions", true, "mindset")?;
    get_timestamp(map, "created_at", "mindset")
}

fn validate_thought(map: &Map<String, Value>) -> Result<()> {
    check_keys(
        map,
        &["type", "parents", "mindset", "operation", "message", "author", "timestamp"],
        &["removals"],
        "thought",
    )?;
    get_oid_list(map, "parents", false, "thought")?; // semantic order (CQ-006)
    get_oid(map, "mindset", "thought")?;
    let operation = get_str(map, "operation", "thought")?;
    if !THOUGHT_OPERATIONS.contains(&operation) {
        return user_err(format!("thought: operation must be one of {THOUGHT_OPERATIONS:?}"));
    }
    get_str(map, "message", "thought")?;
    get_str(map, "author", "thought")?;
    get_timestamp(map, "timestamp", "thought")?;
    if let Some(removals) = map.get("removals") {
        // ADR-0014: durable removal provenance — optional, additive
        let entries = removals
            .as_array()
            .filter(|list| !list.is_empty())
            .ok_or_else(|| {
                CoreError::User("thought: removals must be a non-empty list when present".into())
            })?;
        let mut seen: Vec<String> = Vec::new();
        for entry in entries {
            let entry_map = entry.as_object().ok_or_else(|| {
                CoreError::User("thought: each removal needs exactly {assertion, reason}".into())
            })?;
            if entry_map.len() != 2
                || !entry_map.contains_key("assertion")
                || !entry_map.contains_key("reason")
            {
                return user_err("thought: each removal needs exactly {assertion, reason}");
            }
            let assertion = get_oid(entry_map, "assertion", "thought.removals")?;
            let reason = entry_map.get("reason").and_then(Value::as_str).unwrap_or("");
            if reason.is_empty() {
                return user_err("thought: removal reason must be a non-empty string");
            }
            seen.push(assertion.to_owned());
        }
        let mut sorted = seen.clone();
        sorted.sort();
        sorted.dedup();
        if seen != sorted {
            return user_err("thought: removals must be sorted by assertion and unique");
        }
    }
    Ok(())
}

fn validate_anchor(map: &Map<String, Value>) -> Result<()> {
    check_keys(map, &["type", "name", "target", "created_at", "author"], &[], "anchor")?;
    let name = get_str(map, "name", "anchor")?;
    if !is_ref_segment(name) {
        return user_err("anchor: name must be a valid ref segment");
    }
    get_oid(map, "target", "anchor")?;
    get_timestamp(map, "created_at", "anchor")?;
    get_str(map, "author", "anchor")?;
    Ok(())
}

fn validate_annotation(map: &Map<String, Value>) -> Result<()> {
    check_keys(
        map,
        &["type", "target", "namespace", "body", "author", "created_at", "parents"],
        &[],
        "annotation",
    )?;
    get_oid(map, "target", "annotation")?;
    let namespace = get_str(map, "namespace", "annotation")?;
    if !is_ref_segment(namespace) {
        return user_err("annotation: namespace must be a valid ref segment");
    }
    get_str(map, "body", "annotation")?;
    get_str(map, "author", "annotation")?;
    get_timestamp(map, "created_at", "annotation")?;
    get_oid_list(map, "parents", false, "annotation")?; // chain order
    Ok(())
}

/// Validate an object against its schema; return the object type.
pub fn validate_object(value: &Value) -> Result<&str> {
    let map = match value.as_object() {
        Some(map) => map,
        None => return user_err("object: must be a JSON object"),
    };
    let obj_type = match map.get("type").and_then(Value::as_str) {
        Some(t) if OBJECT_TYPES.contains(&t) => t,
        _ => return user_err(format!("object: type must be one of {OBJECT_TYPES:?}")),
    };
    match obj_type {
        "claim" => validate_claim(map)?,
        "assertion" => validate_assertion(map)?,
        "mindset" => validate_mindset(map)?,
        "thought" => validate_thought(map)?,
        "anchor" => validate_anchor(map)?,
        "annotation" => validate_annotation(map)?,
        _ => unreachable!(),
    }
    Ok(obj_type)
}

/// (object_id, preimage bytes) for a validated object.
pub fn encode_object(value: &Value) -> Result<(String, Vec<u8>)> {
    let obj_type = validate_object(value)?.to_owned();
    let body = canonical_json_bytes(value)?;
    let mut preimage = format!("{} {}", obj_type, body.len()).into_bytes();
    preimage.push(0);
    preimage.extend_from_slice(&body);
    let digest = Sha256::digest(&preimage);
    let mut oid = String::with_capacity(71);
    oid.push_str("sha256:");
    for byte in digest {
        oid.push_str(&format!("{byte:02x}"));
    }
    Ok((oid, preimage))
}
