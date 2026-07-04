//! Repository operations. Port of prototype/cogit/repo.py; semantics
//! contracts: docs/prd, docs/spec, docs/invariants.md.

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::error::{CoreError, Result};
use crate::index::{empty_index, index_is_empty, load_index, save_index, IndexLock};
use crate::objects::is_oid;
use crate::refs::{validate_ref_name, Head, RefStore};
use crate::rerere;
use crate::secrets::reject_suspected_secrets;
use crate::store::ObjectStore;
use crate::time::now_utc;

const DEFAULT_CONFIG: &str = "[core]\n\trepositoryFormatVersion = 1\n[extensions]\n\tobjectFormat = sha256\n";
const LOCK_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(2);

fn user_err<T>(msg: impl Into<String>) -> Result<T> {
    Err(CoreError::User(msg.into()))
}

fn str_set(values: impl IntoIterator<Item = impl Into<String>>) -> BTreeSet<String> {
    values.into_iter().map(Into::into).collect()
}

fn arr_strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_str().map(str::to_owned))
        .collect()
}

pub fn parse_config(text: &str) -> HashMap<String, HashMap<String, String>> {
    let mut sections: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut current: Option<String> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            let name = line[1..line.len() - 1].trim().to_lowercase();
            sections.entry(name.clone()).or_default();
            current = Some(name);
            continue;
        }
        if let (Some(section), Some((key, value))) = (&current, line.split_once('=')) {
            sections
                .get_mut(section)
                .expect("section exists")
                .insert(key.trim().to_owned(), value.trim().to_owned());
        }
    }
    sections
}

/// Create .cogit layout. Idempotent: never destroys existing state (US-001).
pub fn init_repository(path: &Path) -> Result<PathBuf> {
    let cogit_dir = path.join(".cogit");
    for sub in [
        "",
        "objects",
        "tmp",
        "logs",
        "logs/refs/heads",
        "logs/refs/anchors",
        "logs/refs/notes",
        "refs/heads",
        "refs/anchors",
        "refs/notes",
        "refs/remotes",
    ] {
        fs::create_dir_all(cogit_dir.join(sub))?;
    }
    let head = cogit_dir.join("HEAD");
    if !head.exists() {
        fs::write(&head, "ref: refs/heads/main\n")?;
    }
    let config = cogit_dir.join("config");
    if !config.exists() {
        fs::write(&config, DEFAULT_CONFIG)?;
    }
    if !cogit_dir.join("index.json").exists() {
        save_index(&cogit_dir, &empty_index())?;
    }
    Ok(cogit_dir)
}

pub fn find_repository(start: &Path) -> Result<PathBuf> {
    let mut current = start
        .canonicalize()
        .map_err(|_| CoreError::RepoNotFound(format!("no .cogit repository found from '{}'", start.display())))?;
    loop {
        let candidate = current.join(".cogit");
        if candidate.is_dir() {
            return Ok(candidate);
        }
        match current.parent() {
            Some(parent) => current = parent.to_path_buf(),
            None => {
                return Err(CoreError::RepoNotFound(format!(
                    "no .cogit repository found from '{}'",
                    start.display()
                )))
            }
        }
    }
}

pub struct Repository {
    pub cogit_dir: PathBuf,
    pub store: ObjectStore,
    pub refs: RefStore,
}

impl Repository {
    pub fn open(start: &Path) -> Result<Self> {
        let cogit_dir = find_repository(start)?;
        let repo = Repository {
            store: ObjectStore::new(&cogit_dir),
            refs: RefStore::new(&cogit_dir),
            cogit_dir,
        };
        repo.check_format()?;
        Ok(repo)
    }

    fn check_format(&self) -> Result<()> {
        let text = fs::read_to_string(self.cogit_dir.join("config"))
            .map_err(|_| CoreError::RepoNotFound(format!("{}: missing config", self.cogit_dir.display())))?;
        let config = parse_config(&text);
        let version = config.get("core").and_then(|s| s.get("repositoryFormatVersion"));
        if version.map(String::as_str) != Some("1") {
            return Err(CoreError::Unsupported(format!(
                "unsupported repositoryFormatVersion: {version:?}"
            )));
        }
        if let Some(extensions) = config.get("extensions") {
            for (key, value) in extensions {
                if key == "objectFormat" {
                    if value != "sha256" {
                        return Err(CoreError::Unsupported(format!("unsupported objectFormat: {value}")));
                    }
                } else {
                    return Err(CoreError::Unsupported(format!("unknown required extensions: [{key}]")));
                }
            }
        }
        Ok(())
    }

    // -- HEAD / resolution ---------------------------------------------------------

    /// (branch refname or None, thought oid or None)
    pub fn head_info(&self) -> Result<(Option<String>, Option<String>)> {
        match self.refs.read_head()? {
            Head::Symbolic(refname) => {
                let target = self.refs.read_ref(&refname)?;
                Ok((Some(refname), target))
            }
            Head::Detached(oid) => Ok((None, Some(oid))),
        }
    }

    fn looks_like_hex_prefix(name: &str) -> bool {
        let stripped = name.strip_prefix("sha256:").unwrap_or(name);
        (6..=64).contains(&stripped.len())
            && stripped.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    }

    pub fn resolve(&self, name: &str) -> Result<String> {
        if name.is_empty() || name == "HEAD" {
            let (_branch, thought) = self.head_info()?;
            return thought.ok_or_else(|| CoreError::User("resolve: HEAD has no commits yet".into()));
        }
        if is_oid(name) {
            return Ok(name.to_owned());
        }
        if name.len() == 64 && Self::looks_like_hex_prefix(name) {
            return Ok(format!("sha256:{name}"));
        }
        let candidates: Vec<String> = if name.starts_with("refs/") {
            vec![name.to_owned()]
        } else {
            vec![format!("refs/heads/{name}"), format!("refs/anchors/{name}")]
        };
        for refname in candidates {
            if validate_ref_name(&refname).is_err() {
                continue;
            }
            if let Some(target) = self.refs.read_ref(&refname)? {
                if refname.starts_with("refs/anchors/") {
                    let anchor = self.read_typed(&target, "anchor")?;
                    return Ok(anchor["target"].as_str().expect("anchor target").to_owned());
                }
                return Ok(target);
            }
        }
        if Self::looks_like_hex_prefix(name) {
            return self.store.expand_prefix(name);
        }
        user_err(format!("resolve: unknown ref or object '{name}'"))
    }

    /// Full oid, bare 64-hex, or unique prefix -> full oid (no ref lookup).
    pub fn expand_object_id(&self, name: &str) -> Result<String> {
        if is_oid(name) {
            return Ok(name.to_owned());
        }
        self.store.expand_prefix(name)
    }

    pub fn read_typed(&self, oid: &str, expected: &str) -> Result<Value> {
        let obj = self.store.read(oid)?;
        if obj["type"].as_str() != Some(expected) {
            return user_err(format!(
                "{oid} is a {}, expected {expected}",
                obj["type"].as_str().unwrap_or("?")
            ));
        }
        Ok(obj)
    }

    pub fn mindset_assertions(&self, thought_oid: Option<&str>) -> Result<BTreeSet<String>> {
        match thought_oid {
            None => Ok(BTreeSet::new()),
            Some(oid) => {
                let thought = self.read_typed(oid, "thought")?;
                let mindset = self.read_typed(thought["mindset"].as_str().expect("mindset"), "mindset")?;
                Ok(str_set(arr_strings(&mindset["assertions"])))
            }
        }
    }

    // -- staging ------------------------------------------------------------------------

    /// Validate a fact document and write its claim+assertion objects.
    fn write_fact_objects(&self, doc: &Value) -> Result<(String, String, Value)> {
        let map = doc
            .as_object()
            .ok_or_else(|| CoreError::User("add-fact: input must be a JSON object".into()))?;
        for key in map.keys() {
            if key != "claim" && key != "assertion" {
                return user_err(format!("add-fact: unknown top-level fields: [{key}]"));
            }
        }
        if !map.contains_key("assertion") {
            return user_err("add-fact: 'assertion' is required");
        }
        reject_suspected_secrets(doc, "add-fact")?;

        let mut assertion = map["assertion"].as_object().cloned().unwrap_or_default();
        let claim_oid = if let Some(claim_value) = map.get("claim") {
            let mut claim = claim_value.as_object().cloned().unwrap_or_default();
            claim.entry("type".to_owned()).or_insert(json!("claim"));
            let claim_oid = self.store.write(&Value::Object(claim))?;
            if let Some(existing) = assertion.get("claim").and_then(Value::as_str) {
                if existing != claim_oid {
                    return user_err("add-fact: assertion.claim does not match the provided claim object");
                }
            }
            assertion.insert("claim".to_owned(), json!(claim_oid));
            claim_oid
        } else {
            let claim_oid = assertion
                .get("claim")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .filter(|c| is_oid(c));
            match claim_oid {
                Some(oid) if self.store.exists(&oid)? => {
                    self.read_typed(&oid, "claim")?;
                    oid
                }
                _ => return user_err("add-fact: assertion.claim must reference an existing claim"),
            }
        };
        assertion.entry("type".to_owned()).or_insert(json!("assertion"));
        let assertion_value = Value::Object(assertion);
        let assertion_oid = self.store.write(&assertion_value)?;
        Ok((claim_oid, assertion_oid, assertion_value))
    }

    /// Returns (claim_oid, assertion_oid).
    pub fn add_fact(&self, doc: &Value) -> Result<(String, String)> {
        let (claim_oid, assertion_oid, _assertion) = self.write_fact_objects(doc)?;
        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let mut index = load_index(&self.cogit_dir)?;
        self.pin_base_mindset(&mut index)?;
        let staged = index["staged_facts"].as_array_mut().expect("staged");
        if !staged.iter().any(|v| v.as_str() == Some(&assertion_oid)) {
            staged.push(json!(assertion_oid));
            staged.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
        }
        save_index(&self.cogit_dir, &index)?;
        Ok((claim_oid, assertion_oid))
    }

    /// Record one belief as its own thought WITHOUT touching the shared
    /// index (COG-035): mindset = parent's mindset + the new assertion,
    /// published via ref old-target check with retry. Parallel-safe.
    pub fn micro_commit(
        &self,
        doc: &Value,
        message: Option<&str>,
        author: Option<&str>,
        timestamp: Option<&str>,
    ) -> Result<Value> {
        let (claim_oid, assertion_oid, assertion) = self.write_fact_objects(doc)?;
        let claim = self.read_typed(&claim_oid, "claim")?;
        let message = message.map(str::to_owned).unwrap_or_else(|| {
            format!(
                "{}: {} {}",
                claim["kind"].as_str().unwrap_or(""),
                claim["subject"].as_str().unwrap_or(""),
                claim["predicate"].as_str().unwrap_or("")
            )
        });
        let author = author
            .map(str::to_owned)
            .unwrap_or_else(|| assertion["actor"].as_str().unwrap_or("agent").to_owned());
        reject_suspected_secrets(&json!(message), "add-fact")?;

        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        if !index_is_empty(&load_index(&self.cogit_dir)?) {
            return user_err(
                "add-fact: --commit refuses with a non-empty index (staged facts, removals, \
                 conflicts, or merge in progress) — a micro-commit must not invalidate staged work",
            );
        }
        let mut last_error = String::new();
        for _attempt in 0..5 {
            let (branch, parent) = self.head_info()?;
            let base_set = self.mindset_assertions(parent.as_deref())?;
            if base_set.contains(&assertion_oid) {
                return Ok(json!({
                    "claim": claim_oid,
                    "assertion": assertion_oid,
                    "thought": parent,
                    "already_active": true,
                }));
            }
            let mut new_assertions = base_set;
            new_assertions.insert(assertion_oid.clone());
            self.check_negation_consistency(&new_assertions, &empty_index())?;
            let ts = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
            let mindset_oid = self.store.write(&json!({
                "type": "mindset",
                "assertions": new_assertions.iter().collect::<Vec<_>>(),
                "created_at": ts,
            }))?;
            let thought_oid = self.store.write(&json!({
                "type": "thought",
                "parents": parent.iter().cloned().collect::<Vec<_>>(),
                "mindset": mindset_oid,
                "operation": "commit",
                "message": message,
                "author": author,
                "timestamp": ts,
            }))?;
            let publish = match &branch {
                Some(branch) => self
                    .refs
                    .update_ref(branch, &thought_oid, parent.as_deref(), &author, "commit", &message, &ts)
                    .and_then(|_| {
                        self.refs.append_reflog(
                            "HEAD", parent.as_deref(), &thought_oid, &author, "commit", &message, &ts,
                        )
                    }),
                None => self.refs.write_head(
                    &thought_oid, parent.as_deref(), &author, "commit", &message, &ts, parent.as_deref(),
                ),
            };
            match publish {
                Ok(()) => {
                    return Ok(json!({
                        "claim": claim_oid,
                        "assertion": assertion_oid,
                        "thought": thought_oid,
                        "already_active": false,
                    }))
                }
                Err(CoreError::Concurrent(msg)) => last_error = msg, // recompute from new tip
                Err(other) => return Err(other),
            }
        }
        Err(CoreError::Concurrent(format!(
            "add-fact: ref kept moving during micro-commit; giving up after 5 attempts ({last_error})"
        )))
    }

    pub fn remove_fact(&self, assertion_oid: &str, reason: &str) -> Result<&'static str> {
        if !is_oid(assertion_oid) {
            return user_err(format!("remove-fact: invalid assertion id '{assertion_oid}'"));
        }
        if reason.trim().is_empty() {
            return user_err("remove-fact: an explicit --reason is required");
        }
        reject_suspected_secrets(&json!(reason), "remove-fact")?;
        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let mut index = load_index(&self.cogit_dir)?;
        self.pin_base_mindset(&mut index)?;
        let staged = index["staged_facts"].as_array().expect("staged").clone();
        if staged.iter().any(|v| v.as_str() == Some(assertion_oid)) {
            index["staged_facts"] = json!(staged
                .iter()
                .filter(|v| v.as_str() != Some(assertion_oid))
                .cloned()
                .collect::<Vec<_>>());
            save_index(&self.cogit_dir, &index)?;
            return Ok("unstaged");
        }
        let base_set = self.base_assertions(&index)?;
        if !base_set.contains(assertion_oid) {
            return user_err("remove-fact: assertion is neither staged nor active in the base mindset");
        }
        let removed = index["removed_facts"].as_array_mut().expect("removed");
        if !removed.iter().any(|e| e["id"].as_str() == Some(assertion_oid)) {
            removed.push(json!({"id": assertion_oid, "reason": reason}));
            removed.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
        }
        save_index(&self.cogit_dir, &index)?;
        Ok("removed")
    }

    fn pin_base_mindset(&self, index: &mut Value) -> Result<()> {
        let untouched = index["base_mindset"].is_null()
            && index["staged_facts"].as_array().map(Vec::is_empty).unwrap_or(true)
            && index["removed_facts"].as_array().map(Vec::is_empty).unwrap_or(true);
        if untouched {
            let (_branch, thought) = self.head_info()?;
            if let Some(thought_oid) = thought {
                let thought = self.read_typed(&thought_oid, "thought")?;
                index["base_mindset"] = thought["mindset"].clone();
            }
        }
        Ok(())
    }

    fn base_assertions(&self, index: &Value) -> Result<BTreeSet<String>> {
        match index["base_mindset"].as_str() {
            None => Ok(BTreeSet::new()),
            Some(oid) => {
                let mindset = self.read_typed(oid, "mindset")?;
                Ok(str_set(arr_strings(&mindset["assertions"])))
            }
        }
    }

    // -- negation (invariants 24-25) -----------------------------------------------------

    fn negation_group(&self, claim_oid: &str) -> Result<String> {
        let mut seen = BTreeSet::new();
        let mut current = claim_oid.to_owned();
        loop {
            if !seen.insert(current.clone()) {
                return Err(CoreError::Corruption(format!("claims: negation cycle involving {current}")));
            }
            let claim = self.read_typed(&current, "claim")?;
            match claim.get("negates").and_then(Value::as_str) {
                None => return Ok(current),
                Some(negated) => current = negated.to_owned(),
            }
        }
    }

    fn claim_of(&self, assertion_oid: &str) -> Result<String> {
        Ok(self.read_typed(assertion_oid, "assertion")?["claim"]
            .as_str()
            .expect("claim ref")
            .to_owned())
    }

    fn check_negation_consistency(&self, assertion_ids: &BTreeSet<String>, index: &Value) -> Result<()> {
        let mut claim_of = BTreeMap::new();
        for aid in assertion_ids {
            claim_of.insert(aid.clone(), self.claim_of(aid)?);
        }
        let active_claims: BTreeSet<&String> = claim_of.values().collect();
        for (aid, claim_oid) in &claim_of {
            let claim = self.read_typed(claim_oid, "claim")?;
            if let Some(negated) = claim.get("negates").and_then(Value::as_str) {
                if active_claims.contains(&negated.to_owned()) {
                    return user_err(format!(
                        "commit-thought: contradictory mindset — {aid} activates a claim that negates \
                         {negated}, which is still active; remove the original assertion with reason \
                         'refuted' first (invariant 25)"
                    ));
                }
            }
        }
        let mut staged_negated = BTreeSet::new();
        for aid in arr_strings(&index["staged_facts"]) {
            let claim_oid = self.claim_of(&aid)?;
            let claim = self.read_typed(&claim_oid, "claim")?;
            if let Some(negated) = claim.get("negates").and_then(Value::as_str) {
                staged_negated.insert(negated.to_owned());
            }
        }
        if !staged_negated.is_empty() {
            for entry in index["removed_facts"].as_array().into_iter().flatten() {
                let removed_claim = self.claim_of(entry["id"].as_str().expect("removed id"))?;
                if staged_negated.contains(&removed_claim) && entry["reason"].as_str() != Some("refuted") {
                    return user_err(format!(
                        "commit-thought: removal of {} must use reason 'refuted' — a staged assertion \
                         negates its claim (invariant 25)",
                        entry["id"].as_str().unwrap_or("?")
                    ));
                }
            }
        }
        Ok(())
    }

    // -- commit ----------------------------------------------------------------------------

    pub fn commit_thought(&self, message: &str, author: &str, timestamp: Option<&str>) -> Result<String> {
        if message.trim().is_empty() {
            return user_err("commit-thought: --message is required");
        }
        if author.trim().is_empty() {
            return user_err("commit-thought: --author is required");
        }
        reject_suspected_secrets(&json!(message), "commit-thought")?;
        let timestamp = timestamp.map(str::to_owned).unwrap_or_else(now_utc);

        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let index = load_index(&self.cogit_dir)?;
        let conflicts = index["conflicts"].as_array().expect("conflicts");
        if !conflicts.is_empty() {
            return user_err(format!(
                "commit-thought: {} unresolved conflict(s) block commit; use `cogit resolve` or edit index.json",
                conflicts.len()
            ));
        }
        let merge_state = index["merge"].clone();
        let staged_empty = index["staged_facts"].as_array().expect("staged").is_empty();
        let removed_empty = index["removed_facts"].as_array().expect("removed").is_empty();
        if staged_empty && removed_empty && merge_state.is_null() {
            return user_err("commit-thought: nothing staged; use add-fact/remove-fact first");
        }

        let (branch, parent) = self.head_info()?;
        let parent_mindset = match &parent {
            Some(oid) => Some(self.read_typed(oid, "thought")?["mindset"].as_str().unwrap().to_owned()),
            None => None,
        };
        if index["base_mindset"].as_str() != parent_mindset.as_deref() {
            return Err(CoreError::Concurrent(format!(
                "commit-thought: HEAD moved since staging began (staged against {}, HEAD mindset is {})",
                index["base_mindset"].as_str().unwrap_or("null"),
                parent_mindset.as_deref().unwrap_or("null"),
            )));
        }
        if !merge_state.is_null() && merge_state["ours"].as_str() != parent.as_deref() {
            return Err(CoreError::Concurrent(
                "commit-thought: HEAD moved since merge started".into(),
            ));
        }

        let base_set = self.base_assertions(&index)?;
        let removed_ids: BTreeSet<String> = index["removed_facts"]
            .as_array()
            .expect("removed")
            .iter()
            .filter_map(|e| e["id"].as_str().map(str::to_owned))
            .collect();
        let mut new_assertions: BTreeSet<String> = base_set;
        new_assertions.extend(arr_strings(&index["staged_facts"]));
        for removed in &removed_ids {
            new_assertions.remove(removed);
        }
        self.check_negation_consistency(&new_assertions, &index)?;

        let mindset_oid = self.store.write(&json!({
            "type": "mindset",
            "assertions": new_assertions.iter().collect::<Vec<_>>(),
            "created_at": timestamp,
        }))?;
        let (parents, operation) = if merge_state.is_null() {
            (parent.iter().cloned().collect::<Vec<_>>(), "commit")
        } else {
            (
                vec![
                    merge_state["ours"].as_str().unwrap().to_owned(),
                    merge_state["theirs"].as_str().unwrap().to_owned(),
                ],
                "merge",
            )
        };
        let thought_oid = self.store.write(&json!({
            "type": "thought",
            "parents": parents,
            "mindset": mindset_oid,
            "operation": operation,
            "message": message,
            "author": author,
            "timestamp": timestamp,
        }))?;

        match &branch {
            Some(branch) => {
                self.refs
                    .update_ref(branch, &thought_oid, parent.as_deref(), author, operation, message, &timestamp)?;
                self.refs
                    .append_reflog("HEAD", parent.as_deref(), &thought_oid, author, operation, message, &timestamp)?;
            }
            None => {
                // detached: HEAD content must still be the parent we committed from
                self.refs.write_head(
                    &thought_oid,
                    parent.as_deref(),
                    author,
                    operation,
                    message,
                    &timestamp,
                    parent.as_deref(),
                )?;
            }
        }
        save_index(&self.cogit_dir, &empty_index())?;
        Ok(thought_oid)
    }

    // -- branches / checkout ------------------------------------------------------------------

    pub fn branch(&self, name: &str, thought: Option<&str>, actor: &str, timestamp: Option<&str>) -> Result<String> {
        let refname = format!("refs/heads/{name}");
        validate_ref_name(&refname)?;
        if self.refs.read_ref(&refname)?.is_some() {
            return user_err(format!("branch: '{name}' already exists"));
        }
        let target = self.resolve(thought.unwrap_or("HEAD"))?;
        self.read_typed(&target, "thought")?;
        let ts = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
        self.refs.update_ref(
            &refname,
            &target,
            None,
            actor,
            "branch",
            &format!("created from {}", thought.unwrap_or("HEAD")),
            &ts,
        )?;
        Ok(target)
    }

    pub fn list_branches(&self) -> Result<Vec<Value>> {
        let (current, _thought) = self.head_info()?;
        Ok(self
            .refs
            .list_refs("refs/heads")?
            .into_iter()
            .map(|(refname, target)| {
                json!({
                    "name": refname["refs/heads/".len()..],
                    "target": target,
                    "current": Some(&refname) == current.as_ref(),
                })
            })
            .collect())
    }

    /// Returns (mode, thought oid) where mode is "branch" or "detached".
    pub fn checkout(&self, target: &str, actor: &str, timestamp: Option<&str>) -> Result<(String, String)> {
        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let index = load_index(&self.cogit_dir)?;
        if !index_is_empty(&index) {
            return user_err(
                "checkout: index is not empty (staged facts, removals, conflicts, or merge in progress); \
                 commit or clear it first — MVP blocks checkout with a dirty index",
            );
        }
        let timestamp = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
        let old_raw = self.refs.read_head_raw()?;
        let old_thought = match self.refs.parse_head(&old_raw)? {
            Head::Symbolic(refname) => self.refs.read_ref(&refname)?,
            Head::Detached(oid) => Some(oid),
        };

        let branch_ref = if target.starts_with("refs/") {
            target.to_owned()
        } else {
            format!("refs/heads/{target}")
        };
        let is_branch = validate_ref_name(&branch_ref).is_ok() && self.refs.read_ref(&branch_ref)?.is_some();

        let (mode, new_thought) = if is_branch {
            self.refs.write_head(
                &format!("ref: {branch_ref}"),
                old_thought.as_deref(),
                actor,
                "checkout",
                &format!("moving to branch {target}"),
                &timestamp,
                Some(&old_raw),
            )?;
            ("branch".to_owned(), self.refs.read_ref(&branch_ref)?.expect("branch target"))
        } else {
            let new_thought = self.resolve(target)?;
            self.read_typed(&new_thought, "thought")?;
            self.refs.write_head(
                &new_thought,
                old_thought.as_deref(),
                actor,
                "checkout",
                &format!("detached at {target}"),
                &timestamp,
                Some(&old_raw),
            )?;
            ("detached".to_owned(), new_thought)
        };
        save_index(&self.cogit_dir, &empty_index())?;
        Ok((mode, new_thought))
    }

    // -- history ---------------------------------------------------------------------------------

    pub fn ancestry(&self, start_oid: &str) -> Result<BTreeMap<String, Value>> {
        let mut seen = BTreeMap::new();
        let mut stack = vec![start_oid.to_owned()];
        while let Some(oid) = stack.pop() {
            if seen.contains_key(&oid) {
                continue;
            }
            let thought = self.read_typed(&oid, "thought")?;
            stack.extend(arr_strings(&thought["parents"]));
            seen.insert(oid, thought);
        }
        Ok(seen)
    }

    /// Kahn topological order, oldest first; ties broken by (timestamp, oid).
    pub fn topo_oldest_first(&self, thoughts: &BTreeMap<String, Value>) -> Result<Vec<String>> {
        let mut pending: BTreeMap<String, Vec<String>> = thoughts
            .iter()
            .map(|(oid, t)| {
                (
                    oid.clone(),
                    arr_strings(&t["parents"]).into_iter().filter(|p| thoughts.contains_key(p)).collect(),
                )
            })
            .collect();
        let mut emitted = Vec::new();
        let mut done: BTreeSet<String> = BTreeSet::new();
        while !pending.is_empty() {
            let mut ready: Vec<String> = pending
                .iter()
                .filter(|(_oid, parents)| parents.iter().all(|p| done.contains(p)))
                .map(|(oid, _)| oid.clone())
                .collect();
            if ready.is_empty() {
                return Err(CoreError::Corruption("history: cycle detected in thought graph".into()));
            }
            ready.sort_by_key(|oid| (thoughts[oid]["timestamp"].as_str().unwrap_or("").to_owned(), oid.clone()));
            for oid in ready {
                emitted.push(oid.clone());
                done.insert(oid.clone());
                pending.remove(&oid);
            }
        }
        Ok(emitted)
    }

    /// Thought log, newest first.
    pub fn log(&self, start: Option<&str>) -> Result<Vec<Value>> {
        let start_oid = self.resolve(start.unwrap_or("HEAD"))?;
        let thoughts = self.ancestry(&start_oid)?;
        let order = self.topo_oldest_first(&thoughts)?;
        Ok(order
            .into_iter()
            .rev()
            .map(|oid| {
                let mut entry = thoughts[&oid].clone();
                entry["id"] = json!(oid);
                entry
            })
            .collect())
    }

    /// Reflog entries, newest first.
    pub fn reflog(&self, refname: &str) -> Result<Vec<Value>> {
        let refname = if refname != "HEAD" && !refname.starts_with("refs/") {
            format!("refs/heads/{refname}")
        } else {
            refname.to_owned()
        };
        let mut entries = self.refs.read_reflog(&refname)?;
        entries.reverse();
        Ok(entries)
    }

    pub fn is_ancestor(&self, maybe_ancestor: &str, descendant: &str) -> Result<bool> {
        Ok(self.ancestry(descendant)?.contains_key(maybe_ancestor))
    }

    /// Nearest common ancestor by BFS edge distance from b.
    pub fn merge_base(&self, a: &str, b: &str) -> Result<Option<String>> {
        let ancestors_a: BTreeSet<String> = self.ancestry(a)?.into_keys().collect();
        let mut queue = VecDeque::from([b.to_owned()]);
        let mut seen = BTreeSet::new();
        while let Some(oid) = queue.pop_front() {
            if !seen.insert(oid.clone()) {
                continue;
            }
            if ancestors_a.contains(&oid) {
                return Ok(Some(oid));
            }
            let thought = self.read_typed(&oid, "thought")?;
            queue.extend(arr_strings(&thought["parents"]));
        }
        Ok(None)
    }

    // -- diff ---------------------------------------------------------------------------------------

    fn assertions_of(&self, name: &str) -> Result<BTreeSet<String>> {
        let oid = self.resolve(name)?;
        let obj = self.store.read(&oid)?;
        match obj["type"].as_str() {
            Some("mindset") => Ok(str_set(arr_strings(&obj["assertions"]))),
            Some("thought") => {
                let mindset = self.read_typed(obj["mindset"].as_str().unwrap(), "mindset")?;
                Ok(str_set(arr_strings(&mindset["assertions"])))
            }
            other => user_err(format!("diff: {oid} is a {}, expected thought or mindset", other.unwrap_or("?"))),
        }
    }

    pub fn diff(&self, a: &str, b: &str) -> Result<Value> {
        let set_a = self.assertions_of(a)?;
        let set_b = self.assertions_of(b)?;
        Ok(json!({
            "added": set_b.difference(&set_a).collect::<Vec<_>>(),
            "removed": set_a.difference(&set_b).collect::<Vec<_>>(),
            "unchanged": set_a.intersection(&set_b).collect::<Vec<_>>(),
        }))
    }

    // -- merge ---------------------------------------------------------------------------------------

    pub fn merge(&self, target: &str, actor: &str, timestamp: Option<&str>) -> Result<Value> {
        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let timestamp = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
        let index = load_index(&self.cogit_dir)?;
        if !index_is_empty(&index) {
            return user_err("merge: index is not empty; commit or clear it first");
        }
        let (branch, ours) = self.head_info()?;
        let ours = ours.ok_or_else(|| CoreError::User("merge: HEAD has no commits yet".into()))?;
        let theirs = self.resolve(target)?;
        if theirs == ours || self.is_ancestor(&theirs, &ours)? {
            return Ok(json!({"result": "already-up-to-date", "thought": ours}));
        }
        if self.is_ancestor(&ours, &theirs)? {
            let reason = format!("fast-forward to {target}");
            match &branch {
                Some(branch) => {
                    self.refs.update_ref(branch, &theirs, Some(&ours), actor, "merge", &reason, &timestamp)?;
                    self.refs.append_reflog("HEAD", Some(&ours), &theirs, actor, "merge", &reason, &timestamp)?;
                }
                None => {
                    self.refs
                        .write_head(&theirs, Some(&ours), actor, "merge", &reason, &timestamp, Some(&ours))?;
                }
            }
            save_index(&self.cogit_dir, &empty_index())?;
            return Ok(json!({"result": "fast-forward", "thought": theirs}));
        }

        let base = self.merge_base(&ours, &theirs)?;
        let base_set = self.mindset_assertions(base.as_deref())?;
        let ours_set = self.mindset_assertions(Some(&ours))?;
        let theirs_set = self.mindset_assertions(Some(&theirs))?;

        let added_ours: BTreeSet<String> = ours_set.difference(&base_set).cloned().collect();
        let removed_ours: BTreeSet<String> = base_set.difference(&ours_set).cloned().collect();
        let added_theirs: BTreeSet<String> = theirs_set.difference(&base_set).cloned().collect();
        let removed_theirs: BTreeSet<String> = base_set.difference(&theirs_set).cloned().collect();

        // Conflict detection groups by NEGATION GROUP (claim + negates chain).
        let mut claims: BTreeMap<String, String> = BTreeMap::new();
        let mut groups: BTreeMap<String, String> = BTreeMap::new();
        for aid in base_set.iter().chain(&ours_set).chain(&theirs_set) {
            if !claims.contains_key(aid) {
                let claim = self.claim_of(aid)?;
                groups.insert(aid.clone(), self.negation_group(&claim)?);
                claims.insert(aid.clone(), claim);
            }
        }
        let by_group = |ids: &BTreeSet<String>| -> BTreeMap<String, BTreeSet<String>> {
            let mut grouped: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
            for aid in ids {
                grouped.entry(groups[aid].clone()).or_default().insert(aid.clone());
            }
            grouped
        };
        let added_ours_g = by_group(&added_ours);
        let added_theirs_g = by_group(&added_theirs);
        let removed_ours_g = by_group(&removed_ours);
        let removed_theirs_g = by_group(&removed_theirs);

        let mut conflicts: Vec<Value> = Vec::new();
        let mut conflicted_groups: BTreeSet<String> = BTreeSet::new();
        let all_groups: BTreeSet<&String> = added_ours_g.keys().chain(added_theirs_g.keys()).collect();
        for group in all_groups {
            let empty = BTreeSet::new();
            let ours_added = added_ours_g.get(group).unwrap_or(&empty);
            let theirs_added = added_theirs_g.get(group).unwrap_or(&empty);
            let add_add = !ours_added.is_empty() && !theirs_added.is_empty() && ours_added != theirs_added;
            let change_delete = (!ours_added.is_empty() && removed_theirs_g.contains_key(group))
                || (!theirs_added.is_empty() && removed_ours_g.contains_key(group));
            let negation_split = !ours_added.is_empty()
                && !theirs_added.is_empty()
                && ours_added.union(theirs_added).any(|aid| &claims[aid] != group);
            if add_add || change_delete || negation_split {
                conflicted_groups.insert(group.clone());
                conflicts.push(json!({
                    "claim": group,
                    "ours": ours_added.iter().collect::<Vec<_>>(),
                    "theirs": theirs_added.iter().collect::<Vec<_>>(),
                    "base": base_set.iter().filter(|aid| &groups[*aid] == group).collect::<Vec<_>>(),
                }));
            }
        }

        let mut result: BTreeSet<String> = base_set
            .iter()
            .filter(|aid| !removed_ours.contains(*aid) && !removed_theirs.contains(*aid))
            .cloned()
            .collect();
        result.extend(added_ours.iter().cloned());
        result.extend(added_theirs.iter().cloned());
        result.retain(|aid| !conflicted_groups.contains(&groups[aid]));

        // rerere: attach stored suggestions; never auto-apply (US-019)
        for conflict in &mut conflicts {
            let fp = rerere::conflict_fingerprint(conflict);
            if let Some(stored) = rerere::suggestion_for(&self.cogit_dir, conflict) {
                conflict["suggestion"] = json!({"keep": stored["keep"]});
            }
            conflict["fingerprint"] = json!(fp);
        }

        let ours_mindset = self.read_typed(&ours, "thought")?["mindset"].clone();
        let staged: Vec<String> = result.difference(&ours_set).cloned().collect();
        let mut staged_negated: BTreeSet<String> = BTreeSet::new();
        for aid in &staged {
            let claim = self.read_typed(&claims[aid], "claim")?;
            if let Some(negated) = claim.get("negates").and_then(Value::as_str) {
                staged_negated.insert(negated.to_owned());
            }
        }
        let removed_facts: Vec<Value> = ours_set
            .difference(&result)
            .filter(|aid| !conflicted_groups.contains(&groups[*aid]))
            .map(|aid| {
                let reason = if staged_negated.contains(&claims[aid]) { "refuted" } else { "merge" };
                json!({"id": aid, "reason": reason})
            })
            .collect();

        let mut index = empty_index();
        index["base_mindset"] = ours_mindset;
        index["staged_facts"] = json!(staged);
        index["removed_facts"] = json!(removed_facts);
        index["conflicts"] = json!(conflicts);
        index["merge"] = json!({"ours": ours, "theirs": theirs, "base": base});
        save_index(&self.cogit_dir, &index)?;
        Ok(json!({
            "result": if conflicts.is_empty() { "staged" } else { "conflicts" },
            "conflicts": conflicts,
            "staged": index["staged_facts"],
            "removed": index["removed_facts"].as_array().unwrap().iter().map(|e| e["id"].clone()).collect::<Vec<_>>(),
            "base": base,
        }))
    }

    pub fn resolve_conflict(
        &self,
        claim_oid: &str,
        keep: Option<&str>,
        drop: bool,
        use_suggestion: bool,
    ) -> Result<usize> {
        let mode_count = usize::from(keep.is_some()) + usize::from(drop) + usize::from(use_suggestion);
        if mode_count != 1 {
            return user_err("resolve: exactly one of --keep <assertion-id>, --drop, or --suggested is required");
        }
        let _lock = IndexLock::acquire(&self.cogit_dir, LOCK_TIMEOUT)?;
        let mut index = load_index(&self.cogit_dir)?;
        let entry = index["conflicts"]
            .as_array()
            .expect("conflicts")
            .iter()
            .find(|c| c["claim"].as_str() == Some(claim_oid))
            .cloned()
            .ok_or_else(|| CoreError::User(format!("resolve: no recorded conflict for claim {claim_oid}")))?;
        let keep: Option<String> = if use_suggestion {
            match entry.get("suggestion") {
                Some(stored) => stored["keep"].as_str().map(str::to_owned),
                None => {
                    return user_err("resolve: no stored suggestion for this conflict; use --keep or --drop")
                }
            }
        } else {
            keep.map(str::to_owned)
        };
        let candidates: BTreeSet<String> = ["ours", "theirs", "base"]
            .iter()
            .flat_map(|k| arr_strings(&entry[*k]))
            .collect();
        let mut kept: BTreeSet<String> = BTreeSet::new();
        if let Some(keep) = &keep {
            if !candidates.contains(keep) {
                return user_err(format!("resolve: {keep} is not a candidate for this conflict"));
            }
            kept.insert(keep.clone());
        }
        // Resolution defines the FULL assertion set for the conflicted claim.
        let base_set = self.base_assertions(&index)?;
        let mut staged: BTreeSet<String> = str_set(arr_strings(&index["staged_facts"]));
        let active: BTreeSet<String> = base_set.union(&staged).cloned().collect();
        for aid in kept.difference(&active) {
            staged.insert(aid.clone());
        }
        let to_remove: BTreeSet<String> = candidates.difference(&kept).cloned().collect();
        staged.retain(|aid| !to_remove.contains(aid));
        index["staged_facts"] = json!(staged);
        // Choosing a negation over the original IS a refutation (invariant 25).
        let mut kept_negates: BTreeSet<String> = BTreeSet::new();
        for aid in &kept {
            let kept_claim = self.claim_of(aid)?;
            let claim = self.read_typed(&kept_claim, "claim")?;
            if let Some(negated) = claim.get("negates").and_then(Value::as_str) {
                kept_negates.insert(negated.to_owned());
            }
        }
        let removed = index["removed_facts"].as_array_mut().expect("removed");
        for aid in candidates.intersection(&base_set) {
            if kept.contains(aid) {
                continue;
            }
            if !removed.iter().any(|e| e["id"].as_str() == Some(aid)) {
                let removed_claim = self.claim_of(aid)?;
                let reason = if kept_negates.contains(&removed_claim) {
                    "refuted"
                } else {
                    "merge-conflict-resolution"
                };
                removed.push(json!({"id": aid, "reason": reason}));
            }
        }
        removed.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
        let remaining: Vec<Value> = index["conflicts"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["claim"].as_str() != Some(claim_oid))
            .cloned()
            .collect();
        let remaining_len = remaining.len();
        index["conflicts"] = json!(remaining);
        save_index(&self.cogit_dir, &index)?;
        rerere::record_resolution(&self.cogit_dir, &entry, keep.as_deref(), &now_utc())?;
        Ok(remaining_len)
    }

    // -- blame / fact events ----------------------------------------------------------------------------

    pub fn blame_fact(&self, assertion_oid: &str, start: Option<&str>) -> Result<Value> {
        if !is_oid(assertion_oid) {
            return user_err(format!("blame-fact: invalid assertion id '{assertion_oid}'"));
        }
        let assertion = self.read_typed(assertion_oid, "assertion")?;
        let start_oid = self.resolve(start.unwrap_or("HEAD"))?;
        let thoughts = self.ancestry(&start_oid)?;
        let mut mindsets: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for (oid, thought) in &thoughts {
            let mindset = self.read_typed(thought["mindset"].as_str().unwrap(), "mindset")?;
            mindsets.insert(oid.clone(), str_set(arr_strings(&mindset["assertions"])));
        }
        for oid in self.topo_oldest_first(&thoughts)? {
            if !mindsets[&oid].contains(assertion_oid) {
                continue;
            }
            let parents = arr_strings(&thoughts[&oid]["parents"]);
            if parents.iter().all(|p| !mindsets.get(p).map(|m| m.contains(assertion_oid)).unwrap_or(false)) {
                let thought = &thoughts[&oid];
                return Ok(json!({
                    "thought": oid,
                    "message": thought["message"],
                    "author": thought["author"],
                    "timestamp": thought["timestamp"],
                    "operation": thought["operation"],
                    "claim": assertion["claim"],
                    "source": assertion["source"],
                }));
            }
        }
        user_err(format!("blame-fact: {assertion_oid} was never introduced in the selected ancestry"))
    }

    /// Introduction/removal events, newest first (COG-019).
    pub fn fact_events(&self, assertion_oid: &str, start: Option<&str>) -> Result<Vec<Value>> {
        let assertion_oid = self.expand_object_id(assertion_oid)?;
        self.read_typed(&assertion_oid, "assertion")?;
        let start_oid = self.resolve(start.unwrap_or("HEAD"))?;
        let thoughts = self.ancestry(&start_oid)?;
        let mut mindsets: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for (oid, thought) in &thoughts {
            let mindset = self.read_typed(thought["mindset"].as_str().unwrap(), "mindset")?;
            mindsets.insert(oid.clone(), str_set(arr_strings(&mindset["assertions"])));
        }
        let mut events = Vec::new();
        for oid in self.topo_oldest_first(&thoughts)? {
            let present = mindsets[&oid].contains(&assertion_oid);
            let in_parent = arr_strings(&thoughts[&oid]["parents"])
                .iter()
                .any(|p| mindsets.get(p).map(|m| m.contains(&assertion_oid)).unwrap_or(false));
            let event = if present && !in_parent {
                Some("introduced")
            } else if !present && in_parent {
                Some("removed")
            } else {
                None
            };
            if let Some(event) = event {
                let mut entry = thoughts[&oid].clone();
                entry["id"] = json!(oid);
                entry["event"] = json!(event);
                events.push(entry);
            }
        }
        events.reverse();
        Ok(events)
    }

    // -- anchors -----------------------------------------------------------------------------------------

    pub fn anchor(&self, name: &str, thought: &str, author: &str, timestamp: Option<&str>) -> Result<String> {
        let refname = format!("refs/anchors/{name}");
        validate_ref_name(&refname)?;
        if name.contains('/') {
            return user_err("anchor: name must be a single ref segment");
        }
        if self.refs.read_ref(&refname)?.is_some() {
            return user_err(format!("anchor: '{name}' already exists (anchors are fixed in MVP)"));
        }
        let timestamp = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
        let target = self.resolve(thought)?;
        self.read_typed(&target, "thought")?;
        let anchor_oid = self.store.write(&json!({
            "type": "anchor",
            "name": name,
            "target": target,
            "created_at": timestamp,
            "author": author,
        }))?;
        self.refs.update_ref(
            &refname,
            &anchor_oid,
            None,
            author,
            "anchor",
            &format!("{name} -> {target}"),
            &timestamp,
        )?;
        Ok(anchor_oid)
    }

    pub fn list_anchors(&self) -> Result<Vec<Value>> {
        let mut anchors = Vec::new();
        for (refname, target) in self.refs.list_refs("refs/anchors")? {
            let anchor = self.read_typed(&target, "anchor")?;
            anchors.push(json!({
                "name": refname["refs/anchors/".len()..],
                "anchor": target,
                "target": anchor["target"],
                "created_at": anchor["created_at"],
            }));
        }
        Ok(anchors)
    }

    // -- annotations (COG-018) ----------------------------------------------------------------------------

    pub fn annotate(
        &self,
        target: &str,
        body: &str,
        namespace: &str,
        author: &str,
        timestamp: Option<&str>,
    ) -> Result<String> {
        if body.trim().is_empty() {
            return user_err("annotate: --message is required");
        }
        reject_suspected_secrets(&json!(body), "annotate")?;
        let target_oid = if target.starts_with("refs/") {
            self.resolve(target)?
        } else {
            self.expand_object_id(target)?
        };
        let target_obj = self.store.read(&target_oid)?;
        let target_type = target_obj["type"].as_str().unwrap_or("?");
        if !["thought", "assertion", "claim"].contains(&target_type) {
            return user_err(format!(
                "annotate: {target_oid} is a {target_type}; annotatable types are thought, assertion, claim"
            ));
        }
        let refname = format!("refs/notes/{namespace}");
        validate_ref_name(&refname)?;
        if namespace.contains('/') {
            return user_err("annotate: namespace must be a single ref segment");
        }
        let timestamp = timestamp.map(str::to_owned).unwrap_or_else(now_utc);
        let tip = self.refs.read_ref(&refname)?;
        let parents: Vec<String> = tip.iter().cloned().collect();
        let annotation_oid = self.store.write(&json!({
            "type": "annotation",
            "target": target_oid,
            "namespace": namespace,
            "body": body,
            "author": author,
            "created_at": timestamp,
            "parents": parents,
        }))?;
        self.refs.update_ref(
            &refname,
            &annotation_oid,
            tip.as_deref(),
            author,
            "annotate",
            &format!("{namespace}: {target_oid}"),
            &timestamp,
        )?;
        Ok(annotation_oid)
    }

    fn annotation_chain(&self, refname: &str) -> Result<Vec<(String, Value)>> {
        let mut out = Vec::new();
        let mut tip = self.refs.read_ref(refname)?;
        let mut seen = BTreeSet::new();
        while let Some(oid) = tip {
            if !seen.insert(oid.clone()) {
                break;
            }
            let annotation = self.read_typed(&oid, "annotation")?;
            let parents = arr_strings(&annotation["parents"]);
            out.push((oid, annotation));
            tip = parents.first().cloned();
        }
        Ok(out)
    }

    /// Annotations newest-first, optionally filtered by target and namespace.
    pub fn annotations_for(&self, target: Option<&str>, namespace: Option<&str>) -> Result<Vec<Value>> {
        let target_oid = match target {
            Some(t) => Some(self.expand_object_id(t)?),
            None => None,
        };
        let refnames: Vec<String> = match namespace {
            Some(ns) => vec![format!("refs/notes/{ns}")],
            None => self.refs.list_refs("refs/notes")?.into_iter().map(|(r, _t)| r).collect(),
        };
        let mut results = Vec::new();
        for refname in refnames {
            for (oid, annotation) in self.annotation_chain(&refname)? {
                if target_oid.is_none() || annotation["target"].as_str() == target_oid.as_deref() {
                    let mut entry = annotation;
                    entry["id"] = json!(oid);
                    results.push(entry);
                }
            }
        }
        results.sort_by_key(|a| {
            (
                a["created_at"].as_str().unwrap_or("").to_owned(),
                a["id"].as_str().unwrap_or("").to_owned(),
            )
        });
        results.reverse();
        Ok(results)
    }

    /// Map target oid -> annotations (newest first) across all namespaces.
    pub fn annotations_index(&self) -> Result<BTreeMap<String, Vec<Value>>> {
        let mut index: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for entry in self.annotations_for(None, None)? {
            let target = entry["target"].as_str().expect("target").to_owned();
            index.entry(target).or_default().push(entry);
        }
        Ok(index)
    }

    // -- facts / show / recap (COG-028, COG-031) -----------------------------------------------------------

    pub fn fact_row(&self, aid: &str) -> Result<Value> {
        let assertion = self.read_typed(aid, "assertion")?;
        let claim = self.read_typed(assertion["claim"].as_str().unwrap(), "claim")?;
        Ok(json!({
            "assertion": aid,
            "claim": assertion["claim"],
            "kind": claim["kind"],
            "subject": claim["subject"],
            "predicate": claim["predicate"],
            "object": claim["object"],
            "negates": claim.get("negates").cloned().unwrap_or(Value::Null),
            "negation": claim.get("negates").is_some(),
            "qualifiers": claim["qualifiers"],
            "confidence_bps": assertion["confidence_bps"],
            "source": assertion["source"]["type"],
            "source_uri": assertion["source"].get("uri").cloned().unwrap_or(Value::Null),
            "status": assertion["status"],
        }))
    }

    fn row_matches(row: &Value, subject: Option<&str>, predicate: Option<&str>, project: Option<&str>) -> bool {
        if let Some(subject) = subject {
            let actual = row["subject"].as_str().unwrap_or("");
            match subject.strip_suffix('*') {
                Some(prefix) => {
                    if !actual.starts_with(prefix) {
                        return false;
                    }
                }
                None => {
                    if actual != subject {
                        return false;
                    }
                }
            }
        }
        if let Some(predicate) = predicate {
            if row["predicate"].as_str() != Some(predicate) {
                return false;
            }
        }
        if let Some(project) = project {
            if row["qualifiers"]["project"].as_str() != Some(project) {
                return false;
            }
        }
        true
    }

    /// Filters (COG-036/037) are exact URI matching; subject accepts a
    /// trailing '*' prefix wildcard, project matches the claim qualifier.
    pub fn facts(
        &self,
        r#ref: Option<&str>,
        subject: Option<&str>,
        predicate: Option<&str>,
        project: Option<&str>,
    ) -> Result<Value> {
        let thought_oid = self.resolve(r#ref.unwrap_or("HEAD"))?;
        let mut rows: Vec<Value> = Vec::new();
        for aid in self.mindset_assertions(Some(&thought_oid))? {
            let row = self.fact_row(&aid)?;
            if Self::row_matches(&row, subject, predicate, project) {
                rows.push(row);
            }
        }
        Ok(json!({"thought": thought_oid, "facts": rows}))
    }

    pub fn show(&self, r#ref: Option<&str>) -> Result<Value> {
        let thought_oid = self.resolve(r#ref.unwrap_or("HEAD"))?;
        let thought = self.read_typed(&thought_oid, "thought")?;
        let mut out = thought;
        out["id"] = json!(thought_oid);
        out["facts"] = self.facts(Some(&thought_oid), None, None, None)?["facts"].clone();
        Ok(out)
    }

    /// Belief-state digest between two points — context recovery (COG-031).
    /// With no source (COG-036), starts from the NEWEST anchor, or the
    /// root thought when no anchors exist.
    pub fn recap(&self, source: Option<&str>, target: Option<&str>) -> Result<Value> {
        let to_oid = self.resolve(target.unwrap_or("HEAD"))?;
        let mut from_anchor: Option<String> = None;
        let from_oid = match source {
            Some(source) => self.resolve(source)?,
            None => {
                let anchors = self.list_anchors()?;
                match anchors.iter().max_by_key(|a| {
                    (
                        a["created_at"].as_str().unwrap_or("").to_owned(),
                        a["name"].as_str().unwrap_or("").to_owned(),
                    )
                }) {
                    Some(newest) => {
                        from_anchor = newest["name"].as_str().map(str::to_owned);
                        newest["target"].as_str().expect("anchor target").to_owned()
                    }
                    None => {
                        let ancestry = self.ancestry(&to_oid)?;
                        self.topo_oldest_first(&ancestry)?[0].clone()
                    }
                }
            }
        };
        let mut thoughts_out = Vec::new();
        if from_oid != to_oid {
            let ancestry_to = self.ancestry(&to_oid)?;
            if !ancestry_to.contains_key(&from_oid) {
                return user_err("recap: <from> is not an ancestor of <to>; for unrelated points use `cogit diff`");
            }
            let ancestry_from: BTreeSet<String> = self.ancestry(&from_oid)?.into_keys().collect();
            let between: BTreeMap<String, Value> = ancestry_to
                .into_iter()
                .filter(|(oid, _)| !ancestry_from.contains(oid))
                .collect();
            for oid in self.topo_oldest_first(&between)? {
                let t = &between[&oid];
                thoughts_out.push(json!({
                    "id": oid,
                    "message": t["message"],
                    "author": t["author"],
                    "timestamp": t["timestamp"],
                    "operation": t["operation"],
                }));
            }
        }
        let from_set = self.mindset_assertions(Some(&from_oid))?;
        let to_set = self.mindset_assertions(Some(&to_oid))?;
        let added: Vec<Value> = to_set.difference(&from_set).map(|aid| self.fact_row(aid)).collect::<Result<_>>()?;
        let removed: Vec<Value> =
            from_set.difference(&to_set).map(|aid| self.fact_row(aid)).collect::<Result<_>>()?;
        Ok(json!({
            "from": from_oid,
            "from_anchor": from_anchor,
            "same_point": from_oid == to_oid,
            "to": to_oid,
            "thoughts": thoughts_out,
            "added": added,
            "removed": removed,
            "position": self.status()?,
        }))
    }

    // -- status ----------------------------------------------------------------------------------------------

    pub fn status(&self) -> Result<Value> {
        let (branch, thought) = self.head_info()?;
        let index = load_index(&self.cogit_dir)?;
        Ok(json!({
            "branch": branch.as_ref().map(|b| b["refs/heads/".len()..].to_owned()),
            "detached": branch.is_none(),
            "thought": thought,
            "staged": index["staged_facts"],
            "removed": index["removed_facts"],
            "conflicts": index["conflicts"],
            "merge_in_progress": !index["merge"].is_null(),
        }))
    }

    // -- dump (COG-042) ------------------------------------------------------------------

    /// One-call reader surface: active facts, first introducers, anchors,
    /// branches, bounded log, and a recap block — everything a context-free
    /// agent needs to re-anchor without porcelain archaeology.
    pub fn dump(
        &self,
        r#ref: Option<&str>,
        project: Option<&str>,
        since: Option<&str>,
        log_limit: usize,
    ) -> Result<Value> {
        let status = self.status()?;
        let mut doc = json!({
            "position": status,
            "branches": self.list_branches()?,
            "anchors": self.list_anchors()?,
            "thought": Value::Null,
            "facts": [],
            "introducer": {},
            "log": [],
            "recap": {"error": "empty repository: no thoughts yet"},
        });
        if r#ref.is_none() && doc["position"]["thought"].is_null() {
            return Ok(doc);
        }
        let thought_oid = self.resolve(r#ref.unwrap_or("HEAD"))?;
        doc["thought"] = json!(thought_oid);
        let facts = self.facts(Some(&thought_oid), None, None, project)?;
        let rows = facts["facts"].as_array().cloned().unwrap_or_default();
        let active: BTreeSet<String> = rows
            .iter()
            .map(|row| row["assertion"].as_str().unwrap_or_default().to_owned())
            .collect();
        doc["facts"] = json!(rows);
        let thoughts = self.ancestry(&thought_oid)?;
        let order = self.topo_oldest_first(&thoughts)?;
        let mut mindsets: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for oid in &order {
            mindsets.insert(oid.clone(), self.mindset_assertions(Some(oid))?);
        }
        let mut introducer: BTreeMap<String, String> = BTreeMap::new();
        for oid in &order {
            // oldest first == blame-fact's first-introducer rule
            let parents: Vec<String> = thoughts[oid]["parents"]
                .as_array()
                .map(|ps| ps.iter().filter_map(|p| p.as_str().map(str::to_owned)).collect())
                .unwrap_or_default();
            for aid in mindsets[oid].intersection(&active) {
                if introducer.contains_key(aid) {
                    continue;
                }
                let in_parent = parents
                    .iter()
                    .any(|p| mindsets.get(p).map(|m| m.contains(aid)).unwrap_or(false));
                if !in_parent {
                    introducer.insert(aid.clone(), oid.clone());
                }
            }
        }
        doc["introducer"] = json!(introducer);
        let log_rows: Vec<Value> = order
            .iter()
            .rev()
            .take(log_limit)
            .map(|oid| {
                let thought = &thoughts[oid];
                json!({
                    "id": oid,
                    "parents": thought["parents"],
                    "message": thought["message"],
                    "author": thought["author"],
                    "timestamp": thought["timestamp"],
                    "operation": thought["operation"],
                })
            })
            .collect();
        doc["log"] = json!(log_rows);
        doc["recap"] = match self.recap(since, Some(&thought_oid)) {
            Ok(recap) => recap,
            Err(CoreError::User(message)) => json!({"error": message}),
            Err(err) => return Err(err),
        };
        Ok(doc)
    }
}

/// Helper shared by CLI and maintenance: config thresholds map.
pub fn maintenance_config(cogit_dir: &Path) -> HashMap<String, String> {
    fs::read_to_string(cogit_dir.join("config"))
        .ok()
        .map(|text| parse_config(&text).remove("maintenance").unwrap_or_default())
        .unwrap_or_default()
}

/// Convenience: a Map from a Value object (empty map when not an object).
pub fn as_object(value: &Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}
