//! Bisect over thought history (COG-021, CQ-015). Probes are non-mutating:
//! the oracle receives COGIT_THOUGHT/COGIT_MINDSET/COGIT_REPO env vars.

use std::collections::{BTreeMap, BTreeSet};
use std::process::Command;

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::repo::Repository;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Good,
    Bad,
    Skip,
}

impl Verdict {
    fn as_str(self) -> &'static str {
        match self {
            Verdict::Good => "good",
            Verdict::Bad => "bad",
            Verdict::Skip => "skip",
        }
    }
}

/// Oracle runner: exit 0 good, 125 skip, other < 128 bad, >= 128 aborts.
pub fn run_command_oracle(repo: &Repository, command: &str, thought_oid: &str) -> Result<Verdict> {
    let thought = repo.store.read(thought_oid)?;
    let repo_root = repo.cogit_dir.parent().expect("repo root").to_path_buf();
    let status = Command::new("sh")
        .arg("-c")
        .arg(command)
        .env("COGIT_THOUGHT", thought_oid)
        .env("COGIT_MINDSET", thought["mindset"].as_str().unwrap_or(""))
        .env("COGIT_REPO", &repo_root)
        .status()?;
    match status.code() {
        Some(0) => Ok(Verdict::Good),
        Some(125) => Ok(Verdict::Skip),
        Some(code) if (1..128).contains(&code) => Ok(Verdict::Bad),
        other => Err(CoreError::User(format!(
            "bisect-thought: oracle died (exit {other:?}) on {thought_oid}; aborting"
        ))),
    }
}

/// Binary search for the first bad thought between good and bad.
pub fn bisect_thought<F>(repo: &Repository, good: &str, bad: &str, mut runner: F) -> Result<Value>
where
    F: FnMut(&str) -> Result<Verdict>,
{
    let good_oid = repo.resolve(good)?;
    let bad_oid = repo.resolve(bad)?;
    if good_oid == bad_oid {
        return Err(CoreError::User("bisect-thought: good and bad are the same thought".into()));
    }
    let ancestry_bad = repo.ancestry(&bad_oid)?;
    if !ancestry_bad.contains_key(&good_oid) {
        return Err(CoreError::User("bisect-thought: good must be an ancestor of bad".into()));
    }
    let good_set: BTreeSet<String> = repo.ancestry(&good_oid)?.into_keys().collect();
    let candidates: BTreeMap<String, Value> = ancestry_bad
        .into_iter()
        .filter(|(oid, _)| !good_set.contains(oid))
        .collect();
    let order = repo.topo_oldest_first(&candidates)?;
    assert_eq!(order.last(), Some(&bad_oid));

    let mut verdicts: BTreeMap<String, Verdict> = BTreeMap::from([(bad_oid.clone(), Verdict::Bad)]);
    let mut log: Vec<Value> = Vec::new();
    let (mut lo, mut hi) = (0usize, order.len() - 1);
    while lo < hi {
        let window: Vec<usize> = (lo..hi).filter(|i| !verdicts.contains_key(&order[*i])).collect();
        if window.is_empty() {
            return Ok(json!({
                "result": "inconclusive",
                "first_bad": null,
                "range": order[lo..=hi],
                "log": log,
                "candidates": order.len(),
            }));
        }
        let mid = window[window.len() / 2];
        let verdict = runner(&order[mid])?;
        log.push(json!({"thought": order[mid], "verdict": verdict.as_str()}));
        verdicts.insert(order[mid].clone(), verdict);
        match verdict {
            Verdict::Skip => continue,
            Verdict::Bad => hi = mid,
            Verdict::Good => lo = mid + 1,
        }
    }

    let last_good = (0..hi)
        .rev()
        .find(|i| verdicts.get(&order[*i]) == Some(&Verdict::Good))
        .map(|i| i as i64)
        .unwrap_or(-1);
    let suspects: Vec<&String> = ((last_good + 1) as usize..hi)
        .filter(|i| verdicts.get(&order[*i]) == Some(&Verdict::Skip))
        .map(|i| &order[i])
        .collect();
    Ok(json!({
        "result": "found",
        "first_bad": order[hi],
        "skipped_suspects": suspects,
        "log": log,
        "candidates": order.len(),
    }))
}
