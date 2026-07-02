//! Conflict resolution memory (COG-020). Fingerprints MUST match the
//! reference implementation byte-for-byte (shared rerere.json).

use std::fs;
use std::io::Write;
use std::path::Path;

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::canonical::canonical_json_bytes;
use crate::error::Result;

/// Orientation-invariant identity of a conflict shape.
pub fn conflict_fingerprint(conflict: &Value) -> String {
    let side = |key: &str| -> Vec<String> {
        let mut v: Vec<String> = conflict[key]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|x| x.as_str().map(str::to_owned))
            .collect();
        v.sort();
        v
    };
    let mut sides = [side("ours"), side("theirs")];
    sides.sort();
    let shape = json!({
        "claim": conflict["claim"],
        "sides": sides,
        "base": side("base"),
    });
    let digest = Sha256::digest(canonical_json_bytes(&shape).expect("fingerprint shape"));
    let mut out = String::with_capacity(71);
    out.push_str("sha256:");
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

pub fn load_rerere(cogit_dir: &Path) -> Map<String, Value> {
    fs::read_to_string(cogit_dir.join("rerere.json"))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

fn save(cogit_dir: &Path, store: &Map<String, Value>) -> Result<()> {
    let tmp_dir = cogit_dir.join("tmp");
    fs::create_dir_all(&tmp_dir)?;
    let tmp_path = tmp_dir.join(format!("rerere-{}", std::process::id()));
    {
        let mut file = fs::File::create(&tmp_path)?;
        file.write_all(serde_json::to_string_pretty(&Value::Object(store.clone())).unwrap().as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
    }
    fs::rename(&tmp_path, cogit_dir.join("rerere.json"))?;
    Ok(())
}

pub fn record_resolution(cogit_dir: &Path, conflict: &Value, keep: Option<&str>, recorded_at: &str) -> Result<()> {
    let mut store = load_rerere(cogit_dir);
    store.insert(
        conflict_fingerprint(conflict),
        json!({
            "claim": conflict["claim"],
            "keep": keep,
            "recorded_at": recorded_at,
        }),
    );
    save(cogit_dir, &store)
}

pub fn suggestion_for(cogit_dir: &Path, conflict: &Value) -> Option<Value> {
    load_rerere(cogit_dir).get(&conflict_fingerprint(conflict)).cloned()
}

/// Drop entries by fingerprint or by claim id. Returns removed count.
pub fn forget(cogit_dir: &Path, key: &str) -> Result<usize> {
    let mut store = load_rerere(cogit_dir);
    let doomed: Vec<String> = store
        .iter()
        .filter(|(fp, rec)| fp.as_str() == key || rec["claim"].as_str() == Some(key))
        .map(|(fp, _)| fp.clone())
        .collect();
    for fp in &doomed {
        store.remove(fp);
    }
    if !doomed.is_empty() {
        save(cogit_dir, &store)?;
    }
    Ok(doomed.len())
}
