//! Repository pressure metrics (COG-022): header-only scan, corrupt-tolerant,
//! never mutates.

use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::Path;

use flate2::read::ZlibDecoder;
use serde_json::{json, Value};

use crate::error::Result;
use crate::objects::OBJECT_TYPES;
use crate::repo::{maintenance_config, Repository};

fn count_files(path: &Path) -> usize {
    let mut total = 0;
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in fs::read_dir(&dir).into_iter().flatten().filter_map(|e| e.ok()) {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if !p.to_string_lossy().ends_with(".lock") {
                total += 1;
            }
        }
    }
    total
}

pub fn thresholds(cogit_dir: &Path) -> BTreeMap<String, Option<i64>> {
    let mut out: BTreeMap<String, Option<i64>> = BTreeMap::from([
        ("looseObjectsWarn".to_owned(), Some(5000)),
        ("refsWarn".to_owned(), Some(200)),
        ("reflogEntriesWarn".to_owned(), Some(10000)),
        // retention has NO default: reflog expiry is always explicit (COG-024)
        ("reflogRetainEntries".to_owned(), None),
    ]);
    let section = maintenance_config(cogit_dir);
    for (key, value) in section {
        let canonical = out.keys().find(|k| k.eq_ignore_ascii_case(&key)).cloned();
        if let (Some(canonical), Ok(parsed)) = (canonical, value.parse::<i64>()) {
            out.insert(canonical, Some(parsed));
        }
    }
    out
}

pub fn count_objects(repo: &Repository) -> Result<Value> {
    let cogit = &repo.cogit_dir;
    let mut by_type: BTreeMap<&str, u64> = OBJECT_TYPES.iter().map(|t| (*t, 0)).collect();
    let mut corrupt = 0u64;
    let mut disk_bytes = 0u64;
    let objects_dir = cogit.join("objects");
    if objects_dir.is_dir() {
        let mut stack = vec![objects_dir];
        while let Some(dir) = stack.pop() {
            for entry in fs::read_dir(&dir).into_iter().flatten().filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                disk_bytes += entry.metadata().map(|m| m.len()).unwrap_or(0);
                let header_type = fs::read(&path).ok().and_then(|compressed| {
                    let mut decoder = ZlibDecoder::new(compressed.as_slice());
                    let mut preimage = Vec::new();
                    decoder.read_to_end(&mut preimage).ok()?;
                    let nul = preimage.iter().position(|b| *b == 0)?;
                    let header = std::str::from_utf8(&preimage[..nul]).ok()?;
                    Some(header.split(' ').next()?.to_owned())
                });
                match header_type.as_deref() {
                    Some(t) if by_type.contains_key(t) => *by_type.get_mut(t).unwrap() += 1,
                    _ => corrupt += 1,
                }
            }
        }
    }

    let heads = count_files(&cogit.join("refs").join("heads")) as u64;
    let anchors = count_files(&cogit.join("refs").join("anchors")) as u64;

    let mut reflog_entries = 0u64;
    let mut reflog_bytes = 0u64;
    let logs_dir = cogit.join("logs");
    if logs_dir.is_dir() {
        let mut stack = vec![logs_dir];
        while let Some(dir) = stack.pop() {
            for entry in fs::read_dir(&dir).into_iter().flatten().filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else {
                    reflog_bytes += entry.metadata().map(|m| m.len()).unwrap_or(0);
                    if let Ok(text) = fs::read_to_string(&path) {
                        reflog_entries += text.lines().filter(|l| !l.trim().is_empty()).count() as u64;
                    }
                }
            }
        }
    }
    let tmp_files = fs::read_dir(cogit.join("tmp")).map(|d| d.count()).unwrap_or(0) as u64;

    let loose_total: u64 = by_type.values().sum::<u64>() + corrupt;
    let limits = thresholds(cogit);
    let mut warnings: Vec<String> = Vec::new();
    if let Some(Some(limit)) = limits.get("looseObjectsWarn") {
        if loose_total as i64 > *limit {
            warnings.push(format!(
                "loose objects ({loose_total}) exceed threshold {limit}; consider planning maintenance layers (ADR-0006)"
            ));
        }
    }
    if let Some(Some(limit)) = limits.get("refsWarn") {
        if (heads + anchors) as i64 > *limit {
            warnings.push(format!("refs ({}) exceed threshold {limit}", heads + anchors));
        }
    }
    if let Some(Some(limit)) = limits.get("reflogEntriesWarn") {
        if reflog_entries as i64 > *limit {
            warnings.push(format!(
                "reflog entries ({reflog_entries}) exceed threshold {limit}; define a retention policy (OQ-010)"
            ));
        }
    }
    if corrupt > 0 {
        warnings.push(format!("{corrupt} unreadable object file(s); run `cogit verify`"));
    }

    Ok(json!({
        "loose_objects": loose_total,
        "by_type": by_type,
        "corrupt_objects": corrupt,
        "disk_bytes": disk_bytes,
        "heads": heads,
        "anchors": anchors,
        "reflog_entries": reflog_entries,
        "reflog_bytes": reflog_bytes,
        "tmp_files": tmp_files,
        "thresholds": limits,
        "warnings": warnings,
    }))
}
