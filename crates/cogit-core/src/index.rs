//! Staged working memory: .cogit/index.json (repository-layout-v1).
//! Value-based like the reference implementation so conflict entries can
//! carry optional fingerprint/suggestion fields.

use std::fs;
use std::io::Write;
use std::path::Path;

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::objects::is_oid;

pub fn empty_index() -> Value {
    json!({
        "base_mindset": null,
        "staged_facts": [],
        "removed_facts": [],
        "conflicts": [],
        "merge": null,
    })
}

pub fn load_index(cogit_dir: &Path) -> Result<Value> {
    let path = cogit_dir.join("index.json");
    let text = fs::read_to_string(&path)
        .map_err(|_| CoreError::Corruption("index: index.json missing".into()))?;
    let data: Value = serde_json::from_str(&text)
        .map_err(|e| CoreError::Corruption(format!("index: index.json malformed: {e}")))?;
    let map = data
        .as_object()
        .ok_or_else(|| CoreError::Corruption("index: index.json malformed".into()))?;
    for field in ["base_mindset", "staged_facts", "removed_facts", "conflicts", "merge"] {
        if !map.contains_key(field) {
            return Err(CoreError::Corruption("index: index.json missing required fields".into()));
        }
    }
    if !data["base_mindset"].is_null() && !data["base_mindset"].as_str().map(is_oid).unwrap_or(false) {
        return Err(CoreError::Corruption("index: base_mindset invalid".into()));
    }
    for staged in data["staged_facts"].as_array().into_iter().flatten() {
        if !staged.as_str().map(is_oid).unwrap_or(false) {
            return Err(CoreError::Corruption(format!("index: staged fact id invalid: {staged}")));
        }
    }
    for entry in data["removed_facts"].as_array().into_iter().flatten() {
        let id_ok = entry["id"].as_str().map(is_oid).unwrap_or(false);
        let reason_ok = entry["reason"].as_str().map(|r| !r.is_empty()).unwrap_or(false);
        if !id_ok || !reason_ok {
            return Err(CoreError::Corruption(
                "index: removed_facts entries need 'id' and 'reason'".into(),
            ));
        }
    }
    Ok(data)
}

pub fn save_index(cogit_dir: &Path, data: &Value) -> Result<()> {
    let tmp_dir = cogit_dir.join("tmp");
    fs::create_dir_all(&tmp_dir)?;
    let tmp_path = tmp_dir.join(format!("index-{}", std::process::id()));
    {
        let mut file = fs::File::create(&tmp_path)?;
        file.write_all(serde_json::to_string_pretty(data).expect("index json").as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
    }
    fs::rename(&tmp_path, cogit_dir.join("index.json"))?;
    Ok(())
}

pub fn index_is_empty(data: &Value) -> bool {
    data["staged_facts"].as_array().map(Vec::is_empty).unwrap_or(true)
        && data["removed_facts"].as_array().map(Vec::is_empty).unwrap_or(true)
        && data["conflicts"].as_array().map(Vec::is_empty).unwrap_or(true)
        && data["merge"].is_null()
}
