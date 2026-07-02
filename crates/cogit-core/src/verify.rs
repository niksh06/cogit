//! Repository health check. Port of prototype/cogit/verify.py: reports,
//! never repairs; errors mean corruption (exit 3), warnings alone are healthy.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use serde_json::{json, Value};

use crate::error::CoreError;
use crate::index::load_index;
use crate::objects::is_oid;
use crate::refs::{validate_ref_name, Head};
use crate::repo::Repository;

fn finding(findings: &mut Vec<Value>, severity: &str, code: &str, message: String) {
    findings.push(json!({"severity": severity, "code": code, "message": message}));
}

fn arr_strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_str().map(str::to_owned))
        .collect()
}

pub fn verify_repository(repo: &Repository) -> Vec<Value> {
    let mut findings = Vec::new();
    let cogit = &repo.cogit_dir;

    for required in ["HEAD", "config", "index.json"] {
        if !cogit.join(required).is_file() {
            finding(&mut findings, "error", "missing-file", format!("required file missing: {required}"));
        }
    }
    for required_dir in ["objects", "refs/heads", "logs"] {
        if !cogit.join(required_dir).is_dir() {
            finding(&mut findings, "error", "missing-dir", format!("required directory missing: {required_dir}"));
        }
    }

    // -- objects: full read verification, collect typed graph -------------------------
    let mut objects: BTreeMap<String, Value> = BTreeMap::new();
    let objects_dir = cogit.join("objects");
    if objects_dir.is_dir() {
        let mut fanouts: Vec<_> = fs::read_dir(&objects_dir)
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .collect();
        fanouts.sort_by_key(|e| e.file_name());
        for fanout in fanouts {
            if !fanout.path().is_dir() {
                continue;
            }
            let fan = fanout.file_name().to_string_lossy().into_owned();
            let mut rests: Vec<_> = fs::read_dir(fanout.path())
                .into_iter()
                .flatten()
                .filter_map(|e| e.ok())
                .collect();
            rests.sort_by_key(|e| e.file_name());
            for rest in rests {
                let oid = format!("sha256:{fan}{}", rest.file_name().to_string_lossy());
                if !is_oid(&oid) {
                    finding(&mut findings, "error", "bad-path", format!("objects/{fan}/... is not a valid fanout path"));
                    continue;
                }
                match repo.store.read(&oid) {
                    Ok(obj) => {
                        objects.insert(oid, obj);
                    }
                    Err(err) => finding(&mut findings, "error", "corrupt-object", err.to_string()),
                }
            }
        }
    }

    let mut link_findings: Vec<Value> = Vec::new();
    let check_link = |findings: &mut Vec<Value>, owner: &str, oid: &str, expected: &str, code: &str| -> bool {
        match objects.get(oid) {
            None => {
                finding(findings, "error", code, format!("{owner} references missing object {oid}"));
                false
            }
            Some(obj) if obj["type"].as_str() != Some(expected) => {
                finding(
                    findings,
                    "error",
                    code,
                    format!("{owner} references {oid} of type {}, expected {expected}", obj["type"].as_str().unwrap_or("?")),
                );
                false
            }
            _ => true,
        }
    };

    for (oid, obj) in &objects {
        match obj["type"].as_str().unwrap_or("") {
            "thought" => {
                for parent in arr_strings(&obj["parents"]) {
                    check_link(&mut link_findings, oid, &parent, "thought", "missing-parent");
                }
                check_link(&mut link_findings, oid, obj["mindset"].as_str().unwrap_or(""), "mindset", "missing-mindset");
            }
            "mindset" => {
                for aid in arr_strings(&obj["assertions"]) {
                    check_link(&mut link_findings, oid, &aid, "assertion", "missing-assertion");
                }
            }
            "assertion" => {
                check_link(&mut link_findings, oid, obj["claim"].as_str().unwrap_or(""), "claim", "missing-claim");
            }
            "claim" => {
                if let Some(negated) = obj.get("negates").and_then(Value::as_str) {
                    check_link(&mut link_findings, oid, negated, "claim", "missing-negated-claim");
                }
            }
            "anchor" => {
                check_link(&mut link_findings, oid, obj["target"].as_str().unwrap_or(""), "thought", "missing-anchor-target");
            }
            "annotation" => {
                let target = obj["target"].as_str().unwrap_or("");
                match objects.get(target) {
                    None => finding(&mut link_findings, "error", "missing-annotation-target", format!("{oid} annotates missing object {target}")),
                    Some(t) if !["thought", "assertion", "claim"].contains(&t["type"].as_str().unwrap_or("")) => {
                        finding(&mut link_findings, "error", "bad-annotation-target", format!("{oid} annotates a {}", t["type"].as_str().unwrap_or("?")))
                    }
                    _ => {}
                }
                for parent in arr_strings(&obj["parents"]) {
                    check_link(&mut link_findings, oid, &parent, "annotation", "missing-annotation-parent");
                }
            }
            _ => {}
        }
    }

    // -- contradictory mindsets (warning) ---------------------------------------------
    for (oid, obj) in &objects {
        if obj["type"].as_str() != Some("mindset") {
            continue;
        }
        let mut active_claims = BTreeSet::new();
        for aid in arr_strings(&obj["assertions"]) {
            if let Some(assertion) = objects.get(&aid) {
                if assertion["type"].as_str() == Some("assertion") {
                    if let Some(claim) = assertion["claim"].as_str() {
                        active_claims.insert(claim.to_owned());
                    }
                }
            }
        }
        for claim_oid in &active_claims {
            if let Some(claim) = objects.get(claim_oid) {
                if let Some(negated) = claim.get("negates").and_then(Value::as_str) {
                    if active_claims.contains(negated) {
                        finding(
                            &mut link_findings,
                            "warning",
                            "contradictory-mindset",
                            format!("{oid} holds a claim and its negation together ({claim_oid} negates {negated})"),
                        );
                    }
                }
            }
        }
    }

    // -- notes refs: target type + chain namespace consistency -------------------------
    match repo.refs.list_refs("refs/notes") {
        Ok(refs) => {
            for (refname, target) in refs {
                let namespace = refname.rsplit('/').next().unwrap_or("").to_owned();
                if !check_link(&mut link_findings, &refname, &target, "annotation", "bad-ref-target") {
                    continue;
                }
                let mut tip = Some(target);
                let mut seen = BTreeSet::new();
                while let Some(oid) = tip {
                    if !seen.insert(oid.clone()) {
                        break;
                    }
                    let Some(annotation) = objects.get(&oid) else { break };
                    if annotation["namespace"].as_str() != Some(&namespace) {
                        finding(
                            &mut link_findings,
                            "error",
                            "namespace-mismatch",
                            format!(
                                "{oid} carries namespace '{}' but is reachable from {refname}",
                                annotation["namespace"].as_str().unwrap_or("?")
                            ),
                        );
                    }
                    tip = arr_strings(&annotation["parents"]).first().cloned();
                }
            }
        }
        Err(err) => finding(&mut link_findings, "error", "bad-ref", err.to_string()),
    }

    // -- HEAD and refs -------------------------------------------------------------------
    let mut reachable_tips: Vec<String> = Vec::new();
    match repo.refs.read_head() {
        Ok(Head::Detached(oid)) => {
            if check_link(&mut link_findings, "HEAD", &oid, "thought", "bad-head") {
                reachable_tips.push(oid);
            }
        }
        Ok(Head::Symbolic(_)) => {}
        Err(err) => finding(&mut link_findings, "error", "bad-head", err.to_string()),
    }
    for (prefix, expected) in [("refs/heads", "thought"), ("refs/anchors", "anchor")] {
        match repo.refs.list_refs(prefix) {
            Ok(refs) => {
                for (refname, target) in refs {
                    if validate_ref_name(&refname).is_err() {
                        finding(&mut link_findings, "error", "bad-ref-name", format!("invalid ref name {refname}"));
                        continue;
                    }
                    if check_link(&mut link_findings, &refname, &target, expected, "bad-ref-target") {
                        if expected == "thought" {
                            reachable_tips.push(target);
                        } else if let Some(anchor) = objects.get(&target) {
                            if let Some(anchor_target) = anchor["target"].as_str() {
                                reachable_tips.push(anchor_target.to_owned());
                            }
                        }
                    }
                }
            }
            Err(err) => finding(&mut link_findings, "error", "bad-ref", err.to_string()),
        }
    }
    findings.extend(link_findings);

    // -- index ------------------------------------------------------------------------------
    match load_index(cogit) {
        Ok(index) => {
            for aid in arr_strings(&index["staged_facts"]) {
                if !objects.contains_key(&aid) {
                    finding(&mut findings, "error", "index-missing-object", format!("index stages missing object {aid}"));
                }
            }
            if let Some(base) = index["base_mindset"].as_str() {
                if !objects.contains_key(base) {
                    finding(&mut findings, "error", "index-missing-object", format!("index base mindset missing: {base}"));
                }
            }
        }
        Err(CoreError::Corruption(msg)) => finding(&mut findings, "error", "bad-index", msg),
        Err(err) => finding(&mut findings, "error", "bad-index", err.to_string()),
    }

    // -- reflogs -----------------------------------------------------------------------------
    if let Ok(names) = repo.refs.list_reflogs() {
        for name in names {
            if let Err(err) = repo.refs.read_reflog(&name) {
                finding(&mut findings, "error", "bad-reflog", err.to_string());
            }
        }
    }

    // -- dangling thoughts (warning, not corruption) -------------------------------------------
    let mut reachable: BTreeSet<String> = BTreeSet::new();
    let mut stack = reachable_tips;
    while let Some(oid) = stack.pop() {
        if !reachable.insert(oid.clone()) {
            continue;
        }
        if let Some(obj) = objects.get(&oid) {
            stack.extend(arr_strings(&obj["parents"]));
        }
    }
    for (oid, obj) in &objects {
        if obj["type"].as_str() == Some("thought") && !reachable.contains(oid) {
            finding(&mut findings, "warning", "dangling-thought", format!("{oid} is not reachable from any ref"));
        }
    }

    findings
}
