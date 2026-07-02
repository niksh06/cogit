//! Refs, HEAD, and reflogs: lockfile updates with old-target checks.
//! Port of prototype/cogit/refs.py (ADR-0010 protocol, COG-014 HEAD checks).

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::objects::is_oid;

pub fn validate_ref_name(name: &str) -> Result<()> {
    let invalid = || CoreError::User(format!("refs: invalid ref name '{name}'"));
    if name.is_empty()
        || name.starts_with('/')
        || name.ends_with('/')
        || name.ends_with(".lock")
        || name.contains("@{")
        || name.contains('\\')
        || name.contains("..")
    {
        return Err(invalid());
    }
    for segment in name.split('/') {
        let seg_ok = !segment.is_empty()
            && segment
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'.' || b == b'_' || b == b'-');
        if !seg_ok {
            return Err(CoreError::User(format!(
                "refs: invalid ref segment '{segment}' in '{name}'"
            )));
        }
    }
    Ok(())
}

#[derive(Debug, PartialEq, Eq)]
pub enum Head {
    Symbolic(String),
    Detached(String),
}

pub struct RefStore {
    cogit_dir: PathBuf,
}

impl RefStore {
    pub fn new(cogit_dir: &Path) -> Self {
        RefStore {
            cogit_dir: cogit_dir.to_path_buf(),
        }
    }

    fn ref_path(&self, name: &str) -> PathBuf {
        name.split('/').fold(self.cogit_dir.clone(), |p, s| p.join(s))
    }

    fn log_path(&self, name: &str) -> PathBuf {
        name.split('/').fold(self.cogit_dir.join("logs"), |p, s| p.join(s))
    }

    // -- HEAD -----------------------------------------------------------------

    pub fn read_head_raw(&self) -> Result<String> {
        fs::read_to_string(self.cogit_dir.join("HEAD"))
            .map(|s| s.trim().to_owned())
            .map_err(|_| CoreError::Corruption("refs: HEAD missing".into()))
    }

    pub fn parse_head(&self, content: &str) -> Result<Head> {
        if let Some(refname) = content.strip_prefix("ref: ") {
            let refname = refname.trim();
            validate_ref_name(refname)?;
            return Ok(Head::Symbolic(refname.to_owned()));
        }
        if is_oid(content) {
            return Ok(Head::Detached(content.to_owned()));
        }
        Err(CoreError::Corruption(format!("refs: HEAD invalid: '{content}'")))
    }

    pub fn read_head(&self) -> Result<Head> {
        self.parse_head(&self.read_head_raw()?)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn write_head(
        &self,
        value: &str,
        old_target: Option<&str>,
        actor: &str,
        operation: &str,
        reason: &str,
        timestamp: &str,
        expected_raw: Option<&str>,
    ) -> Result<()> {
        if let Some(refname) = value.strip_prefix("ref: ") {
            validate_ref_name(refname)?;
        } else if !is_oid(value) {
            return Err(CoreError::User(format!("refs: invalid HEAD value '{value}'")));
        }
        let path = self.cogit_dir.join("HEAD");
        self.locked_replace(&path, &format!("{value}\n"), expected_raw)?;
        let log_target = if let Some(refname) = value.strip_prefix("ref: ") {
            self.read_ref(refname)?.unwrap_or_else(|| refname.to_owned())
        } else {
            value.to_owned()
        };
        self.append_reflog("HEAD", old_target, &log_target, actor, operation, reason, timestamp)
    }

    // -- plain refs -------------------------------------------------------------

    pub fn read_ref(&self, name: &str) -> Result<Option<String>> {
        validate_ref_name(name)?;
        let path = self.ref_path(name);
        if !path.is_file() {
            return Ok(None);
        }
        let content = fs::read_to_string(&path)?.trim().to_owned();
        if !is_oid(&content) {
            return Err(CoreError::Corruption(format!(
                "refs: {name} has invalid target '{content}'"
            )));
        }
        Ok(Some(content))
    }

    pub fn list_refs(&self, prefix: &str) -> Result<Vec<(String, String)>> {
        let base = self.ref_path(prefix);
        let mut out = Vec::new();
        if !base.is_dir() {
            return Ok(out);
        }
        let mut stack = vec![base];
        while let Some(dir) = stack.pop() {
            let mut entries: Vec<_> = fs::read_dir(&dir)?.filter_map(|e| e.ok()).collect();
            entries.sort_by_key(|e| e.file_name());
            for entry in entries {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else if !path.to_string_lossy().ends_with(".lock") {
                    let rel = path
                        .strip_prefix(&self.cogit_dir)
                        .expect("under cogit dir")
                        .to_string_lossy()
                        .replace(std::path::MAIN_SEPARATOR, "/");
                    if let Some(target) = self.read_ref(&rel)? {
                        out.push((rel, target));
                    }
                }
            }
        }
        out.sort();
        Ok(out)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn update_ref(
        &self,
        name: &str,
        new_target: &str,
        expected_old: Option<&str>,
        actor: &str,
        operation: &str,
        reason: &str,
        timestamp: &str,
    ) -> Result<()> {
        validate_ref_name(name)?;
        if !is_oid(new_target) {
            return Err(CoreError::User(format!("refs: invalid target '{new_target}'")));
        }
        let path = self.ref_path(name);
        fs::create_dir_all(path.parent().expect("ref parent"))?;
        let lock_path = path.with_extension("lock");
        let lock = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|_| CoreError::Concurrent(format!("refs: {name} is locked by another process")))?;
        let result = (|| -> Result<()> {
            let current = self.read_ref(name)?;
            if current.as_deref() != expected_old {
                return Err(CoreError::Concurrent(format!(
                    "refs: {name} moved (expected {}, found {})",
                    expected_old.unwrap_or("null"),
                    current.as_deref().unwrap_or("null"),
                )));
            }
            let mut lock = &lock;
            lock.write_all(format!("{new_target}\n").as_bytes())?;
            lock.sync_all()?;
            fs::rename(&lock_path, &path)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&lock_path);
            return result;
        }
        self.append_reflog(name, expected_old, new_target, actor, operation, reason, timestamp)
    }

    // -- reflog --------------------------------------------------------------------

    #[allow(clippy::too_many_arguments)]
    pub fn append_reflog(
        &self,
        name: &str,
        old_target: Option<&str>,
        new_target: &str,
        actor: &str,
        operation: &str,
        reason: &str,
        timestamp: &str,
    ) -> Result<()> {
        if actor.chars().any(char::is_whitespace) {
            return Err(CoreError::User("reflog: actor must not contain whitespace".into()));
        }
        let reason = reason.split_whitespace().collect::<Vec<_>>().join(" ");
        let reason = if reason.is_empty() { "-".to_owned() } else { reason };
        let line = format!(
            "{} {} {} {} {}: {}\n",
            old_target.unwrap_or("null"),
            new_target,
            timestamp,
            actor,
            operation,
            reason
        );
        let path = self.log_path(name);
        fs::create_dir_all(path.parent().expect("log parent"))?;
        let mut file = fs::OpenOptions::new().create(true).append(true).open(&path).map_err(|e| {
            CoreError::Corruption(format!(
                "reflog: {name} moved but journal append failed; operational history incomplete: {e}"
            ))
        })?;
        file.write_all(line.as_bytes()).and_then(|_| file.sync_all()).map_err(|e| {
            CoreError::Corruption(format!(
                "reflog: {name} moved but journal append failed; operational history incomplete: {e}"
            ))
        })
    }

    /// Parsed reflog entries, oldest first.
    pub fn read_reflog(&self, name: &str) -> Result<Vec<Value>> {
        let path = self.log_path(name);
        if !path.is_file() {
            return Ok(Vec::new());
        }
        let mut entries = Vec::new();
        for (line_no, line) in fs::read_to_string(&path)?.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            let parts: Vec<&str> = line.splitn(5, ' ').collect();
            let parsed = if parts.len() == 5 {
                parts[4].split_once(": ")
            } else {
                None
            };
            match parsed {
                Some((op, reason)) if !op.contains(' ') => entries.push(json!({
                    "old": parts[0],
                    "new": parts[1],
                    "ts": parts[2],
                    "actor": parts[3],
                    "op": op,
                    "reason": reason,
                })),
                _ => {
                    return Err(CoreError::Corruption(format!(
                        "reflog: {name}:{} unparseable line",
                        line_no + 1
                    )))
                }
            }
        }
        Ok(entries)
    }

    pub fn list_reflogs(&self) -> Result<Vec<String>> {
        let logs_dir = self.cogit_dir.join("logs");
        let mut out = Vec::new();
        if !logs_dir.is_dir() {
            return Ok(out);
        }
        let mut stack = vec![logs_dir.clone()];
        while let Some(dir) = stack.pop() {
            for entry in fs::read_dir(&dir)?.filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                } else {
                    let rel = path
                        .strip_prefix(&logs_dir)
                        .expect("under logs")
                        .to_string_lossy()
                        .replace(std::path::MAIN_SEPARATOR, "/");
                    out.push(rel);
                }
            }
        }
        out.sort();
        Ok(out)
    }

    /// Trim a reflog to its newest `keep` entries (COG-024). Returns (kept, dropped).
    pub fn expire_reflog(&self, name: &str, keep: usize, dry_run: bool) -> Result<(usize, usize)> {
        if keep < 1 {
            return Err(CoreError::User("reflog expire: --keep must be >= 1".into()));
        }
        let entries = self.read_reflog(name)?;
        let dropped = entries.len().saturating_sub(keep);
        if dropped == 0 || dry_run {
            return Ok((entries.len() - dropped, dropped));
        }
        let path = self.log_path(name);
        let content = fs::read_to_string(&path)?;
        let lines: Vec<&str> = content.lines().filter(|l| !l.trim().is_empty()).collect();
        let tail: String = lines[lines.len() - keep..]
            .iter()
            .map(|l| format!("{l}\n"))
            .collect();
        self.locked_replace(&path, &tail, None)?;
        Ok((keep, dropped))
    }

    // -- shared helpers ---------------------------------------------------------------

    pub fn locked_replace(&self, path: &Path, content: &str, expected: Option<&str>) -> Result<()> {
        let lock_path = PathBuf::from(format!("{}.lock", path.display()));
        let lock = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|_| {
                CoreError::Concurrent(format!("refs: {} is locked by another process", path.display()))
            })?;
        let result = (|| -> Result<()> {
            if let Some(expected) = expected {
                let current = fs::read_to_string(path).ok().map(|s| s.trim().to_owned());
                if current.as_deref() != Some(expected.trim()) {
                    return Err(CoreError::Concurrent(format!(
                        "refs: {} moved concurrently (expected '{}', found '{}')",
                        path.file_name().unwrap_or_default().to_string_lossy(),
                        expected.trim(),
                        current.as_deref().unwrap_or("null"),
                    )));
                }
            }
            let mut lock = &lock;
            lock.write_all(content.as_bytes())?;
            lock.sync_all()?;
            fs::rename(&lock_path, path)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&lock_path);
        }
        result
    }
}
