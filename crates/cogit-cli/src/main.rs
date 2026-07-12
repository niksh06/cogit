//! Cogit CLI (docs/spec/cli-contract.md). Porcelain over cogit-core;
//! behavior parity with the Python reference CLI (prototype/cogit/cli.py).

use std::io::Read;
use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use serde_json::{json, Value};

use cogit_core::bisect::{bisect_thought, run_command_oracle};
use cogit_core::canonical::parse_json;
use cogit_core::error::{CoreError, Result};
use cogit_core::maintenance::{count_objects, thresholds};
use cogit_core::objects::encode_object;
use cogit_core::repo::{init_repository, Repository};
use cogit_core::rerere;
use cogit_core::time::now_utc;
use cogit_core::verify::verify_repository;

#[derive(Parser)]
#[command(
    name = "cogit",
    version = concat!(env!("CARGO_PKG_VERSION"), " (rs)"),
    about = "Cogit: version control for agent cognition and reasoning provenance."
)]
struct Cli {
    /// repository path (default: nearest .cogit upward)
    #[arg(long, global = true)]
    repo: Option<PathBuf>,
    #[command(subcommand)]
    command: Cmd,
}

#[derive(Subcommand)]
#[allow(clippy::large_enum_variant)] // one-shot CLI dispatch; variant size is irrelevant
enum Cmd {
    /// create a .cogit repository
    Init { path: Option<PathBuf> },
    /// compute (and optionally write) an object id
    HashObject {
        #[arg(long = "type")]
        object_type: String,
        #[arg(long)]
        write: bool,
        file: String,
        #[arg(long)]
        json: bool,
    },
    /// print a decoded, verified object
    CatObject { object_id: String },
    /// write claim+assertion and stage the assertion
    AddFact {
        /// JSON file, inline JSON, or '-' for stdin
        fact: Option<String>,
        #[arg(long)]
        kind: Option<String>,
        #[arg(long)]
        subject: Option<String>,
        #[arg(long)]
        predicate: Option<String>,
        #[arg(long = "object")]
        object_value: Option<String>,
        #[arg(long = "object-json")]
        object_json: Option<String>,
        #[arg(long = "qualifier")]
        qualifiers: Vec<String>,
        #[arg(long)]
        negates: Option<String>,
        /// assertion id this belief derives from (repeatable, ADR-0013)
        #[arg(long = "premise")]
        premises: Vec<String>,
        #[arg(long)]
        source: Option<String>,
        #[arg(long)]
        confidence: Option<i64>,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long, default_value = "cli")]
        method: String,
        #[arg(long = "asserted-at")]
        asserted_at: Option<String>,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        commit: bool,
        #[arg(long, short)]
        message: Option<String>,
        #[arg(long)]
        author: Option<String>,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// stage removal of an active assertion
    RemoveFact {
        assertion_id: String,
        #[arg(long)]
        reason: String,
        #[arg(long)]
        json: bool,
    },
    /// one atomic thought: retire the target with reason 'superseded' and assert a
    /// replacement in the same claim family (COG-056)
    SupersedeFact {
        /// active assertion to supersede
        assertion_id: String,
        #[arg(long = "object")]
        object_value: Option<String>,
        #[arg(long = "object-json")]
        object_json: Option<String>,
        #[arg(long)]
        source: Option<String>,
        #[arg(long)]
        confidence: Option<i64>,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long, default_value = "cli")]
        method: String,
        #[arg(long = "asserted-at")]
        asserted_at: Option<String>,
        #[arg(long = "premise")]
        premises: Vec<String>,
        #[arg(long, short)]
        message: Option<String>,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// one atomic thought: remove ALL active assertions of the target's claim with
    /// reason 'refuted' and activate its negation (COG-056)
    RefuteFact {
        /// active assertion whose claim is being refuted
        assertion_id: String,
        #[arg(long)]
        source: Option<String>,
        #[arg(long)]
        confidence: Option<i64>,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long, default_value = "cli")]
        method: String,
        #[arg(long = "asserted-at")]
        asserted_at: Option<String>,
        #[arg(long = "premise")]
        premises: Vec<String>,
        #[arg(long, short)]
        message: Option<String>,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// one atomic thought: remove active assertions with an explicit reason,
    /// without asserting falsity (COG-056)
    RetireFact {
        /// active assertion(s) to retire
        #[arg(required = true)]
        assertion_ids: Vec<String>,
        #[arg(long)]
        reason: String,
        #[arg(long, default_value = "agent")]
        author: String,
        #[arg(long, short)]
        message: Option<String>,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// commit staged facts as a thought
    CommitThought {
        #[arg(long, short)]
        message: String,
        #[arg(long)]
        author: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// create a branch (or list branches)
    Branch {
        name: Option<String>,
        thought: Option<String>,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// switch HEAD to a branch or detach at a thought
    Checkout {
        target: String,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// show current position and staged state
    Status {
        #[arg(long)]
        json: bool,
    },
    /// walk thought history (or reflog with -g)
    Log {
        #[arg(short = 'g')]
        reflog: bool,
        r#ref: Option<String>,
        #[arg(long = "introduced-fact")]
        introduced_fact: Option<String>,
        #[arg(long = "removed-fact")]
        removed_fact: Option<String>,
        #[arg(long)]
        annotations: bool,
        #[arg(long)]
        json: bool,
    },
    /// compare two thoughts or mindsets
    Diff {
        a: String,
        b: String,
        #[arg(long)]
        unchanged: bool,
        #[arg(long)]
        json: bool,
    },
    /// conservative fact-set merge into HEAD
    Merge {
        target: String,
        #[arg(long, default_value = "agent")]
        actor: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// resolve a recorded merge conflict for a claim
    Resolve {
        claim_id: String,
        #[arg(long)]
        keep: Option<String>,
        #[arg(long)]
        drop: bool,
        #[arg(long)]
        suggested: bool,
        #[arg(long)]
        json: bool,
    },
    /// list or forget remembered conflict resolutions
    Rerere {
        #[arg(long)]
        forget: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// first thought that introduced a fact
    BlameFact {
        fact_id: String,
        r#ref: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// belief-state digest between two points (context recovery)
    Recap {
        source: Option<String>,
        target: Option<String>,
        /// shared journal: scope rows and thoughts to this project (COG-053)
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// list active facts of a thought (default: HEAD)
    Facts {
        r#ref: Option<String>,
        #[arg(long)]
        subject: Option<String>,
        #[arg(long)]
        predicate: Option<String>,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// case-insensitive substring search over beliefs — cogit's git-grep (COG-068)
    Search {
        pattern: String,
        #[arg(long = "ref")]
        r#ref: Option<String>,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        history: bool,
        #[arg(long, default_value_t = 50)]
        limit: usize,
        #[arg(long)]
        json: bool,
    },
    /// one-call reader surface: facts+introducers+anchors+log+recap (JSON only)
    Dump {
        r#ref: Option<String>,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        since: Option<String>,
        #[arg(long = "limit-log", default_value_t = 50)]
        limit_log: usize,
    },
    /// thought header plus its active facts
    Show {
        r#ref: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// append an annotation to a thought/assertion/claim
    Annotate {
        target: String,
        #[arg(long, short)]
        message: String,
        #[arg(long, default_value = "notes")]
        namespace: String,
        #[arg(long, default_value = "agent")]
        author: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// list annotations for a target (newest first)
    Annotations {
        target: Option<String>,
        #[arg(long)]
        namespace: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// binary-search the first bad thought between good and bad
    BisectThought {
        #[arg(long)]
        good: String,
        #[arg(long)]
        bad: String,
        #[arg(long)]
        run: String,
        #[arg(long = "log")]
        log_file: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// trim reflogs to the newest N entries (explicit, destructive)
    ReflogExpire {
        #[arg(long)]
        keep: Option<usize>,
        #[arg(long)]
        r#ref: Option<String>,
        #[arg(long)]
        all: bool,
        #[arg(long = "dry-run")]
        dry_run: bool,
        #[arg(long)]
        json: bool,
    },
    /// repository pressure metrics (never mutates)
    CountObjects {
        #[arg(long)]
        json: bool,
    },
    /// check repository health (reports, never repairs)
    Verify {
        #[arg(long)]
        json: bool,
    },
    /// record a named milestone (or list anchors)
    Anchor {
        name: Option<String>,
        thought_id: Option<String>,
        #[arg(long, default_value = "agent")]
        author: String,
        #[arg(long)]
        timestamp: Option<String>,
        #[arg(long)]
        json: bool,
    },
}

fn short(oid: &str) -> &str {
    oid.strip_prefix("sha256:").map(|h| &h[..12]).unwrap_or(oid)
}

fn pretty(value: &Value) -> String {
    serde_json::to_string_pretty(value).expect("json")
}

fn open_repo(repo_arg: &Option<PathBuf>) -> Result<Repository> {
    Repository::open(repo_arg.as_deref().unwrap_or(Path::new(".")))
}

fn load_json_arg(value: &str) -> Result<Value> {
    if Path::new(value).is_file() {
        return parse_json(&std::fs::read_to_string(value)?);
    }
    if value.trim_start().starts_with('{') {
        return parse_json(value.trim());
    }
    Err(CoreError::User(format!(
        "'{value}' is neither a JSON object nor an existing file"
    )))
}

/// Assertion object for supersede-fact / refute-fact (COG-056).
#[allow(clippy::too_many_arguments)]
fn build_lifecycle_assertion(
    repo: &Repository,
    source: &Option<String>,
    confidence: Option<i64>,
    actor: &str,
    method: &str,
    asserted_at: &Option<String>,
    premises: &[String],
    command: &str,
) -> Result<Value> {
    let mut missing: Vec<&str> = Vec::new();
    if source.is_none() {
        missing.push("--source");
    }
    if confidence.is_none() {
        missing.push("--confidence");
    }
    if !missing.is_empty() {
        return Err(CoreError::User(format!("{command}: requires {}", missing.join(", "))));
    }
    let (source_type, source_uri) = source.as_ref().unwrap().split_once(':').map_or_else(
        || (source.clone().unwrap(), None),
        |(t, u)| (t.to_owned(), Some(u.to_owned())),
    );
    let mut source_obj = json!({"type": source_type});
    if let Some(uri) = source_uri {
        source_obj["uri"] = json!(uri);
    }
    let mut assertion = json!({
        "type": "assertion",
        "status": "asserted",
        "source": source_obj,
        "confidence_bps": confidence.unwrap(),
        "asserted_at": asserted_at.clone().unwrap_or_else(now_utc),
        "actor": actor,
        "method": {"type": method},
    });
    if !premises.is_empty() {
        let mut expanded = premises
            .iter()
            .map(|p| repo.expand_object_id(p))
            .collect::<Result<Vec<_>>>()?;
        expanded.sort();
        expanded.dedup();
        assertion["premises"] = json!(expanded);
    }
    Ok(assertion)
}

#[allow(clippy::too_many_arguments)]
fn build_shorthand_doc(
    kind: &Option<String>,
    subject: &Option<String>,
    predicate: &Option<String>,
    object_value: &Option<String>,
    object_json: &Option<String>,
    qualifiers: &[String],
    negates: &Option<String>,
    source: &Option<String>,
    confidence: Option<i64>,
    actor: &str,
    method: &str,
    asserted_at: &Option<String>,
) -> Result<Value> {
    let mut missing: Vec<&str> = Vec::new();
    for (flag, present) in [
        ("--kind", kind.is_some()),
        ("--subject", subject.is_some()),
        ("--predicate", predicate.is_some()),
        ("--source", source.is_some()),
        ("--confidence", confidence.is_some()),
    ] {
        if !present {
            missing.push(flag);
        }
    }
    if object_value.is_none() && object_json.is_none() {
        missing.push("--object (or --object-json)");
    }
    if !missing.is_empty() {
        return Err(CoreError::User(format!(
            "add-fact: shorthand form requires {}",
            missing.join(", ")
        )));
    }
    if object_value.is_some() && object_json.is_some() {
        return Err(CoreError::User("add-fact: use either --object or --object-json, not both".into()));
    }
    let obj_value = match object_json {
        Some(text) => parse_json(text)?,
        None => json!(object_value.clone().unwrap()),
    };
    let mut quals = serde_json::Map::new();
    for pair in qualifiers {
        let (key, value) = pair
            .split_once('=')
            .ok_or_else(|| CoreError::User(format!("add-fact: --qualifier expects K=V, got '{pair}'")))?;
        quals.insert(key.to_owned(), json!(value));
    }
    let (source_type, source_uri) = source.as_ref().unwrap().split_once(':').map_or_else(
        || (source.clone().unwrap(), None),
        |(t, u)| (t.to_owned(), Some(u.to_owned())),
    );
    let mut source_obj = json!({"type": source_type});
    if let Some(uri) = source_uri {
        source_obj["uri"] = json!(uri);
    }
    let mut claim = json!({
        "type": "claim",
        "kind": kind,
        "subject": subject,
        "predicate": predicate,
        "object": obj_value,
        "qualifiers": quals,
    });
    if let Some(negates) = negates {
        let negates = if negates.starts_with("sha256:") {
            negates.clone()
        } else {
            format!("sha256:{negates}")
        };
        claim["negates"] = json!(negates);
    }
    Ok(json!({
        "claim": claim,
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": source_obj,
            "confidence_bps": confidence,
            "asserted_at": asserted_at.clone().unwrap_or_else(now_utc),
            "actor": actor,
            "method": {"type": method},
        },
    }))
}

/// Negations must be unmistakable (COG-040): the row asserts the claim is
/// FALSE, not a belief in the printed value.
fn render_object(row: &Value) -> String {
    if row["negates"].is_null() {
        row["object"].to_string()
    } else {
        format!(
            "NOT {} (negates {})",
            row["object"],
            short(row["negates"].as_str().unwrap_or(""))
        )
    }
}

fn print_fact_rows(rows: &[Value]) {
    if rows.is_empty() {
        println!("(no active facts)");
        return;
    }
    for row in rows {
        println!(
            "{}  {}  {} {} {}  conf={} src={}",
            short(row["assertion"].as_str().unwrap_or("")),
            row["kind"].as_str().unwrap_or(""),
            row["subject"].as_str().unwrap_or(""),
            row["predicate"].as_str().unwrap_or(""),
            render_object(row),
            row["confidence_bps"],
            row["source"].as_str().unwrap_or("")
        );
    }
}

fn print_annotation(entry: &Value, indent: &str) {
    println!(
        "{indent}[{}] {} {} {}",
        entry["namespace"].as_str().unwrap_or(""),
        short(entry["id"].as_str().unwrap_or("")),
        entry["author"].as_str().unwrap_or(""),
        entry["created_at"].as_str().unwrap_or("")
    );
    println!("{indent}  {}", entry["body"].as_str().unwrap_or(""));
}

fn run(cli: Cli) -> Result<i32> {
    match cli.command {
        Cmd::Init { path } => {
            let cogit_dir = init_repository(path.as_deref().unwrap_or(Path::new(".")))?;
            println!("initialized cogit repository at {}", cogit_dir.display());
            Ok(0)
        }
        Cmd::HashObject { object_type, write, file, json } => {
            let mut obj = load_json_arg(&file)?;
            if obj["type"].is_null() {
                obj["type"] = json!(object_type);
            }
            if obj["type"].as_str() != Some(&object_type) {
                return Err(CoreError::User(format!(
                    "hash-object: --type {object_type} does not match object type {}",
                    obj["type"]
                )));
            }
            let oid = if write {
                open_repo(&cli.repo)?.store.write(&obj)?
            } else {
                encode_object(&obj)?.0
            };
            println!("{}", if json { json!({"object_id": oid}).to_string() } else { oid });
            Ok(0)
        }
        Cmd::CatObject { object_id } => {
            let repo = open_repo(&cli.repo)?;
            let obj = repo.store.read(&repo.expand_object_id(&object_id)?)?;
            println!("{}", pretty(&obj));
            Ok(0)
        }
        Cmd::AddFact {
            fact, kind, subject, predicate, object_value, object_json, qualifiers, negates,
            premises, source, confidence, actor, method, asserted_at, project, commit, message,
            author, timestamp, json,
        } => {
            let repo = open_repo(&cli.repo)?;
            if fact.is_some() && kind.is_some() {
                return Err(CoreError::User(
                    "add-fact: use either a JSON document or shorthand flags, not both".into(),
                ));
            }
            let doc = if fact.as_deref() == Some("-") {
                let mut text = String::new();
                std::io::stdin().read_to_string(&mut text)?;
                parse_json(&text)?
            } else if let Some(fact) = &fact {
                load_json_arg(fact)?
            } else if kind.is_some() {
                build_shorthand_doc(
                    &kind, &subject, &predicate, &object_value, &object_json, &qualifiers,
                    &negates, &source, confidence, &actor, &method, &asserted_at,
                )?
            } else {
                return Err(CoreError::User(
                    "add-fact: provide a JSON document, '-' for stdin, or shorthand flags (--kind ...)".into(),
                ));
            };
            let mut doc = doc;
            if let Some(project) = &project {
                if let Some(claim) = doc.get_mut("claim").and_then(Value::as_object_mut) {
                    let quals = claim
                        .entry("qualifiers".to_owned())
                        .or_insert_with(|| json!({}));
                    if let Some(quals) = quals.as_object_mut() {
                        quals.entry("project".to_owned()).or_insert_with(|| json!(project));
                    }
                }
            }
            if !premises.is_empty() {
                let assertion = doc
                    .get_mut("assertion")
                    .and_then(Value::as_object_mut)
                    .ok_or_else(|| {
                        CoreError::User("add-fact: --premise requires an assertion document".into())
                    })?;
                let mut expanded: Vec<String> = premises
                    .iter()
                    .map(|p| repo.expand_object_id(p))
                    .collect::<Result<_>>()?;
                expanded.sort_unstable();
                expanded.dedup();
                assertion.insert("premises".to_owned(), json!(expanded));
            }
            if commit {
                // atomic micro-commit: bypasses the shared index (COG-035)
                let result =
                    repo.micro_commit(&doc, message.as_deref(), author.as_deref(), timestamp.as_deref())?;
                if json {
                    println!("{result}");
                    return Ok(0);
                }
                println!("claim     {}", result["claim"].as_str().unwrap_or(""));
                if result["already_active"].as_bool().unwrap_or(false) {
                    println!("already active at {}", result["thought"].as_str().unwrap_or("null"));
                } else {
                    println!("asserted  {}", result["assertion"].as_str().unwrap_or(""));
                    println!("committed {}", result["thought"].as_str().unwrap_or(""));
                }
                return Ok(0);
            }
            let (claim_oid, assertion_oid) = repo.add_fact(&doc)?;
            if json {
                println!("{}", json!({"claim": claim_oid, "assertion": assertion_oid}));
                return Ok(0);
            }
            println!("claim     {claim_oid}");
            println!("staged    {assertion_oid}");
            Ok(0)
        }
        Cmd::RemoveFact { assertion_id, reason, json } => {
            let repo = open_repo(&cli.repo)?;
            let oid = repo.expand_object_id(&assertion_id)?;
            let outcome = repo.remove_fact(&oid, &reason)?;
            if json {
                println!("{}", json!({"outcome": outcome, "assertion": oid}));
            } else {
                println!("{outcome}  {oid}");
            }
            Ok(0)
        }
        Cmd::SupersedeFact {
            assertion_id, object_value, object_json, source, confidence, actor, method,
            asserted_at, premises, message, timestamp, json,
        } => {
            let repo = open_repo(&cli.repo)?;
            if object_value.is_none() && object_json.is_none() {
                return Err(CoreError::User(
                    "supersede-fact: provide the replacement --object (or --object-json)".into(),
                ));
            }
            if object_value.is_some() && object_json.is_some() {
                return Err(CoreError::User(
                    "supersede-fact: use either --object or --object-json, not both".into(),
                ));
            }
            let new_object = match &object_json {
                Some(text) => parse_json(text)?,
                None => json!(object_value.clone().unwrap()),
            };
            let assertion = build_lifecycle_assertion(
                &repo, &source, confidence, &actor, &method, &asserted_at, &premises,
                "supersede-fact",
            )?;
            let result = repo.supersede_fact(
                &assertion_id, &new_object, &assertion, message.as_deref(), timestamp.as_deref(),
            )?;
            if json {
                println!("{result}");
            } else {
                println!("superseded {}", result["old_assertion"].as_str().unwrap_or(""));
                println!("asserted   {}", result["assertion"].as_str().unwrap_or(""));
                println!("committed  {}", result["thought"].as_str().unwrap_or(""));
            }
            Ok(0)
        }
        Cmd::RefuteFact {
            assertion_id, source, confidence, actor, method, asserted_at, premises, message,
            timestamp, json,
        } => {
            let repo = open_repo(&cli.repo)?;
            let assertion = build_lifecycle_assertion(
                &repo, &source, confidence, &actor, &method, &asserted_at, &premises,
                "refute-fact",
            )?;
            let result = repo.refute_fact(
                &assertion_id, &assertion, message.as_deref(), timestamp.as_deref(),
            )?;
            if json {
                println!("{result}");
            } else {
                for oid in result["refuted_assertions"].as_array().cloned().unwrap_or_default() {
                    println!("refuted   {}", oid.as_str().unwrap_or(""));
                }
                println!("negation  {}", result["negation"]["assertion"].as_str().unwrap_or(""));
                println!("committed {}", result["thought"].as_str().unwrap_or(""));
            }
            Ok(0)
        }
        Cmd::RetireFact { assertion_ids, reason, author, message, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.retire_fact(
                &assertion_ids, &reason, &author, message.as_deref(), timestamp.as_deref(),
            )?;
            if json {
                println!("{result}");
            } else {
                for oid in result["retired"].as_array().cloned().unwrap_or_default() {
                    println!("retired   {}", oid.as_str().unwrap_or(""));
                }
                println!("committed {}", result["thought"].as_str().unwrap_or(""));
            }
            Ok(0)
        }
        Cmd::CommitThought { message, author, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            let thought = repo.commit_thought(&message, &author, timestamp.as_deref())?;
            if json {
                println!("{}", json!({"thought": thought}));
            } else {
                println!("committed {thought}");
            }
            Ok(0)
        }
        Cmd::Branch { name, thought, actor, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            match name {
                None => {
                    let branches = repo.list_branches()?;
                    if json {
                        println!("{}", pretty(&json!(branches)));
                    } else {
                        for branch in branches {
                            let marker = if branch["current"].as_bool().unwrap_or(false) { "*" } else { " " };
                            println!("{marker} {} {}", branch["name"].as_str().unwrap(), short(branch["target"].as_str().unwrap()));
                        }
                    }
                }
                Some(name) => {
                    let target = repo.branch(&name, thought.as_deref(), &actor, timestamp.as_deref())?;
                    if json {
                        println!("{}", json!({"branch": name, "target": target}));
                    } else {
                        println!("branch {name} -> {}", short(&target));
                    }
                }
            }
            Ok(0)
        }
        Cmd::Checkout { target, actor, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            let (mode, thought) = repo.checkout(&target, &actor, timestamp.as_deref())?;
            if json {
                println!("{}", json!({"mode": mode, "thought": thought}));
            } else if mode == "branch" {
                println!("switched to branch {target} at {}", short(&thought));
            } else {
                println!("detached HEAD at {}", short(&thought));
            }
            Ok(0)
        }
        Cmd::Status { json } => {
            let repo = open_repo(&cli.repo)?;
            let status = repo.status()?;
            if json {
                println!("{}", pretty(&status));
                return Ok(0);
            }
            if status["detached"].as_bool().unwrap_or(false) {
                println!("detached HEAD at {}", short(status["thought"].as_str().unwrap_or("null")));
            } else {
                println!(
                    "on branch {} at {}",
                    status["branch"].as_str().unwrap_or("?"),
                    short(status["thought"].as_str().unwrap_or("null"))
                );
            }
            let staged = status["staged"].as_array().unwrap();
            println!("staged facts:   {}", staged.len());
            for oid in staged {
                println!("  + {}", oid.as_str().unwrap());
            }
            let removed = status["removed"].as_array().unwrap();
            println!("removed facts:  {}", removed.len());
            for entry in removed {
                println!("  - {} ({})", entry["id"].as_str().unwrap(), entry["reason"].as_str().unwrap());
            }
            let conflicts = status["conflicts"].as_array().unwrap();
            println!("conflicts:      {}", conflicts.len());
            for conflict in conflicts {
                let hint = if conflict.get("suggestion").is_some() {
                    "  (remembered resolution available: --suggested)"
                } else {
                    ""
                };
                println!("  ! claim {}{hint}", conflict["claim"].as_str().unwrap());
            }
            if status["merge_in_progress"].as_bool().unwrap_or(false) {
                println!("merge in progress");
            }
            Ok(0)
        }
        Cmd::Log { reflog, r#ref, introduced_fact, removed_fact, annotations, json } => {
            let repo = open_repo(&cli.repo)?;
            if introduced_fact.is_some() || removed_fact.is_some() {
                if reflog || (introduced_fact.is_some() && removed_fact.is_some()) {
                    return Err(CoreError::User(
                        "log: --introduced-fact/--removed-fact are mutually exclusive and incompatible with -g".into(),
                    ));
                }
                let (fact, wanted) = match &introduced_fact {
                    Some(f) => (f.clone(), "introduced"),
                    None => (removed_fact.clone().unwrap(), "removed"),
                };
                let events: Vec<Value> = repo
                    .fact_events(&fact, r#ref.as_deref())?
                    .into_iter()
                    .filter(|e| e["event"].as_str() == Some(wanted))
                    .collect();
                if json {
                    println!("{}", pretty(&json!(events)));
                } else {
                    for event in events {
                        println!("{}  {}", event["event"].as_str().unwrap(), event["id"].as_str().unwrap());
                        println!("author:   {}", event["author"].as_str().unwrap());
                        println!("date:     {}", event["timestamp"].as_str().unwrap());
                        println!("\n    {}\n", event["message"].as_str().unwrap());
                    }
                }
                return Ok(0);
            }
            if reflog {
                let entries = repo.reflog(r#ref.as_deref().unwrap_or("HEAD"))?;
                if json {
                    println!("{}", pretty(&json!(entries)));
                } else {
                    for (i, entry) in entries.iter().enumerate() {
                        let old = entry["old"].as_str().unwrap_or("null");
                        let was = if old == "null" { "null" } else { short(old) };
                        println!(
                            "{} {}@{{{i}}}: {}: {} ({} {}, was {})",
                            short(entry["new"].as_str().unwrap()),
                            r#ref.as_deref().unwrap_or("HEAD"),
                            entry["op"].as_str().unwrap(),
                            entry["reason"].as_str().unwrap(),
                            entry["actor"].as_str().unwrap(),
                            entry["ts"].as_str().unwrap(),
                            was
                        );
                    }
                }
                return Ok(0);
            }
            let mut thoughts = repo.log(r#ref.as_deref())?;
            let index = if annotations { repo.annotations_index()? } else { Default::default() };
            if json {
                if annotations {
                    for thought in &mut thoughts {
                        let id = thought["id"].as_str().unwrap().to_owned();
                        thought["annotations"] = json!(index.get(&id).cloned().unwrap_or_default());
                    }
                }
                println!("{}", pretty(&json!(thoughts)));
                return Ok(0);
            }
            for thought in thoughts {
                println!("thought {}", thought["id"].as_str().unwrap());
                let parents = thought["parents"].as_array().unwrap();
                if parents.len() > 1 {
                    let short_parents: Vec<&str> = parents.iter().map(|p| short(p.as_str().unwrap())).collect();
                    println!("merge:    {}", short_parents.join(" "));
                }
                println!("author:   {}", thought["author"].as_str().unwrap());
                println!("date:     {}", thought["timestamp"].as_str().unwrap());
                println!("op:       {}", thought["operation"].as_str().unwrap());
                println!("\n    {}\n", thought["message"].as_str().unwrap());
                if let Some(entries) = index.get(thought["id"].as_str().unwrap()) {
                    for entry in entries {
                        print_annotation(entry, "    ");
                    }
                }
            }
            Ok(0)
        }
        Cmd::Diff { a, b, unchanged, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.diff(&a, &b)?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            for oid in result["added"].as_array().unwrap() {
                println!("+ {}", oid.as_str().unwrap());
            }
            for oid in result["removed"].as_array().unwrap() {
                println!("- {}", oid.as_str().unwrap());
            }
            if unchanged {
                for oid in result["unchanged"].as_array().unwrap() {
                    println!("= {}", oid.as_str().unwrap());
                }
            }
            Ok(0)
        }
        Cmd::Merge { target, actor, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.merge(&target, &actor, timestamp.as_deref())?;
            let has_conflicts = result["conflicts"].as_array().map(|c| !c.is_empty()).unwrap_or(false);
            if json {
                println!("{}", pretty(&result));
                return Ok(if has_conflicts { 1 } else { 0 });
            }
            match result["result"].as_str().unwrap() {
                "already-up-to-date" => println!("already up to date"),
                "fast-forward" => println!("fast-forward to {}", short(result["thought"].as_str().unwrap())),
                _ => {
                    println!(
                        "merge staged: +{} -{}",
                        result["staged"].as_array().map(Vec::len).unwrap_or(0),
                        result["removed"].as_array().map(Vec::len).unwrap_or(0)
                    );
                    if has_conflicts {
                        for conflict in result["conflicts"].as_array().unwrap() {
                            println!("CONFLICT claim {}", conflict["claim"].as_str().unwrap());
                            println!("  ours:   {}", conflict["ours"]);
                            println!("  theirs: {}", conflict["theirs"]);
                            if let Some(suggestion) = conflict.get("suggestion") {
                                let remembered = suggestion["keep"].as_str().unwrap_or("drop");
                                println!("  remembered resolution: {remembered}");
                                println!(
                                    "  apply with: cogit resolve {} --suggested",
                                    short(conflict["claim"].as_str().unwrap())
                                );
                            }
                        }
                        println!("resolve conflicts, then run `cogit commit-thought`");
                        return Ok(1);
                    }
                    println!("run `cogit commit-thought` to record the merge thought");
                }
            }
            Ok(0)
        }
        Cmd::Resolve { claim_id, keep, drop, suggested, json } => {
            let repo = open_repo(&cli.repo)?;
            let claim = repo.expand_object_id(&claim_id)?;
            let keep = match keep {
                Some(keep) => Some(repo.expand_object_id(&keep)?),
                None => None,
            };
            let remaining = repo.resolve_conflict(&claim, keep.as_deref(), drop, suggested)?;
            if json {
                println!("{}", json!({"remaining_conflicts": remaining}));
            } else {
                println!("resolved; {remaining} conflict(s) remaining");
            }
            Ok(0)
        }
        Cmd::Rerere { forget, json } => {
            let repo = open_repo(&cli.repo)?;
            if let Some(key) = forget {
                let mut removed = rerere::forget(&repo.cogit_dir, &key)?;
                if removed == 0 && !key.starts_with("sha256:") {
                    if let Ok(expanded) = repo.expand_object_id(&key) {
                        removed = rerere::forget(&repo.cogit_dir, &expanded)?;
                    }
                }
                if json {
                    println!("{}", json!({"forgotten": removed}));
                } else {
                    println!("forgot {removed} stored resolution(s)");
                }
                return Ok(0);
            }
            let store = rerere::load_rerere(&repo.cogit_dir);
            if json {
                println!("{}", pretty(&Value::Object(store)));
                return Ok(0);
            }
            if store.is_empty() {
                println!("(no stored resolutions)");
                return Ok(0);
            }
            for (fingerprint, record) in store {
                let outcome = record["keep"].as_str().unwrap_or("drop").to_owned();
                println!(
                    "{}  claim {}  -> {}  ({})",
                    short(&fingerprint),
                    short(record["claim"].as_str().unwrap_or("")),
                    outcome,
                    record["recorded_at"].as_str().unwrap_or("")
                );
            }
            Ok(0)
        }
        Cmd::BlameFact { fact_id, r#ref, json } => {
            let repo = open_repo(&cli.repo)?;
            let oid = repo.expand_object_id(&fact_id)?;
            let result = repo.blame_fact(&oid, r#ref.as_deref())?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            println!("introduced by {}", result["thought"].as_str().unwrap());
            println!("message:  {}", result["message"].as_str().unwrap());
            println!("author:   {}", result["author"].as_str().unwrap());
            println!("date:     {}", result["timestamp"].as_str().unwrap());
            println!("claim:    {}", result["claim"].as_str().unwrap());
            println!("source:   {}", result["source"]);
            Ok(0)
        }
        Cmd::Recap { source, target, project, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.recap(source.as_deref(), target.as_deref(), project.as_deref())?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            let position = &result["position"];
            let where_ = if position["detached"].as_bool().unwrap_or(false) {
                "detached HEAD".to_owned()
            } else {
                format!("branch {}", position["branch"].as_str().unwrap_or("?"))
            };
            let thoughts = result["thoughts"].as_array().unwrap();
            println!(
                "recap {} -> {} ({} thought(s))",
                short(result["from"].as_str().unwrap()),
                short(result["to"].as_str().unwrap()),
                thoughts.len()
            );
            for thought in thoughts {
                println!(
                    "  {} {} {:7} {}",
                    short(thought["id"].as_str().unwrap()),
                    thought["timestamp"].as_str().unwrap(),
                    thought["operation"].as_str().unwrap(),
                    thought["message"].as_str().unwrap()
                );
            }
            let added = result["added"].as_array().unwrap();
            let removed = result["removed"].as_array().unwrap();
            println!("beliefs: +{} -{}", added.len(), removed.len());
            for row in added {
                println!(
                    "  + {}  {} {} {}  conf={}",
                    row["kind"].as_str().unwrap(),
                    row["subject"].as_str().unwrap(),
                    row["predicate"].as_str().unwrap(),
                    render_object(row),
                    row["confidence_bps"]
                );
            }
            for row in removed {
                println!(
                    "  - {}  {} {} {}",
                    row["kind"].as_str().unwrap(),
                    row["subject"].as_str().unwrap(),
                    row["predicate"].as_str().unwrap(),
                    render_object(row)
                );
            }
            let merge_note = if position["merge_in_progress"].as_bool().unwrap_or(false) {
                ", merge in progress"
            } else {
                ""
            };
            println!(
                "position: {} at {}{}",
                where_,
                short(position["thought"].as_str().unwrap_or("null")),
                merge_note
            );
            Ok(0)
        }
        Cmd::Search { pattern, r#ref, project, history, limit, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.search(&pattern, r#ref.as_deref(), project.as_deref(), history, limit)?;
            if json {
                println!("{result}");
            } else {
                println!(
                    "search '{}': {} match(es)",
                    result["pattern"].as_str().unwrap_or(""),
                    result["total"]
                );
                for row in result["matches"].as_array().cloned().unwrap_or_default() {
                    let flag = if row["active"].as_bool().unwrap_or(false) { ' ' } else { '×' };
                    let fields: Vec<String> = row["matched_in"]
                        .as_array()
                        .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_owned)).collect())
                        .unwrap_or_default();
                    println!(
                        "{flag} {} {} = {}  <- {}",
                        row["subject"].as_str().unwrap_or(""),
                        row["predicate"].as_str().unwrap_or(""),
                        row["object"],
                        fields.join(",")
                    );
                }
            }
            Ok(0)
        }
        Cmd::Dump { r#ref, project, since, limit_log } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.dump(r#ref.as_deref(), project.as_deref(), since.as_deref(), limit_log)?;
            println!("{}", pretty(&result));
            Ok(0)
        }
        Cmd::Facts { r#ref, subject, predicate, project, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.facts(r#ref.as_deref(), subject.as_deref(), predicate.as_deref(), project.as_deref())?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            let rows = result["facts"].as_array().unwrap();
            println!("facts at {} ({} active)", short(result["thought"].as_str().unwrap()), rows.len());
            print_fact_rows(rows);
            Ok(0)
        }
        Cmd::Show { r#ref, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = repo.show(r#ref.as_deref())?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            println!("thought {}", result["id"].as_str().unwrap());
            let parents = result["parents"].as_array().unwrap();
            if parents.len() > 1 {
                let short_parents: Vec<&str> = parents.iter().map(|p| short(p.as_str().unwrap())).collect();
                println!("merge:    {}", short_parents.join(" "));
            }
            println!("author:   {}", result["author"].as_str().unwrap());
            println!("date:     {}", result["timestamp"].as_str().unwrap());
            println!("op:       {}", result["operation"].as_str().unwrap());
            println!("\n    {}\n", result["message"].as_str().unwrap());
            print_fact_rows(result["facts"].as_array().unwrap());
            Ok(0)
        }
        Cmd::Annotate { target, message, namespace, author, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            let oid = repo.annotate(&target, &message, &namespace, &author, timestamp.as_deref())?;
            if json {
                println!("{}", json!({"annotation": oid, "namespace": namespace}));
            } else {
                println!("annotated {oid} ({namespace})");
            }
            Ok(0)
        }
        Cmd::Annotations { target, namespace, json } => {
            let repo = open_repo(&cli.repo)?;
            let entries = repo.annotations_for(target.as_deref(), namespace.as_deref())?;
            if json {
                println!("{}", pretty(&json!(entries)));
            } else if entries.is_empty() {
                println!("(no annotations)");
            } else {
                for entry in entries {
                    print_annotation(&entry, "");
                }
            }
            Ok(0)
        }
        Cmd::BisectThought { good, bad, run, log_file, json } => {
            let repo = open_repo(&cli.repo)?;
            let result = bisect_thought(&repo, &good, &bad, |oid| run_command_oracle(&repo, &run, oid))?;
            let log_lines: Vec<String> = result["log"]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| format!("{} {}", e["thought"].as_str().unwrap(), e["verdict"].as_str().unwrap()))
                .collect();
            if let Some(path) = log_file {
                let mut content = format!("# bisect-thought good={good} bad={bad} run={run}\n");
                content.push_str(&log_lines.join("\n"));
                content.push('\n');
                std::fs::write(path, content)?;
            }
            let found = result["result"].as_str() == Some("found");
            if json {
                println!("{}", pretty(&result));
                return Ok(if found { 0 } else { 1 });
            }
            for line in &log_lines {
                println!("{line}");
            }
            if !found {
                println!("inconclusive: every remaining candidate was skipped");
                for oid in result["range"].as_array().unwrap() {
                    println!("  ? {}", oid.as_str().unwrap());
                }
                return Ok(1);
            }
            let thought = repo.store.read(result["first_bad"].as_str().unwrap())?;
            println!("first bad thought: {}", result["first_bad"].as_str().unwrap());
            println!("message:  {}", thought["message"].as_str().unwrap());
            println!("author:   {}", thought["author"].as_str().unwrap());
            println!("date:     {}", thought["timestamp"].as_str().unwrap());
            for oid in result["skipped_suspects"].as_array().unwrap() {
                println!("warning: skipped candidate could be earlier: {}", oid.as_str().unwrap());
            }
            Ok(0)
        }
        Cmd::ReflogExpire { keep, r#ref, all, dry_run, json } => {
            let repo = open_repo(&cli.repo)?;
            if r#ref.is_some() == all {
                return Err(CoreError::User("reflog-expire: pass exactly one of --ref <name> or --all".into()));
            }
            let keep = match keep {
                Some(keep) => keep,
                None => match thresholds(&repo.cogit_dir).get("reflogRetainEntries") {
                    Some(Some(n)) if *n > 0 => *n as usize,
                    _ => {
                        return Err(CoreError::User(
                            "reflog-expire: no --keep given and no [maintenance] reflogRetainEntries configured".into(),
                        ))
                    }
                },
            };
            let names = if all { repo.refs.list_reflogs()? } else { vec![r#ref.unwrap()] };
            let mut results = Vec::new();
            for name in names {
                let (kept, dropped) = repo.refs.expire_reflog(&name, keep, dry_run)?;
                results.push(json!({"ref": name, "kept": kept, "dropped": dropped}));
            }
            if json {
                println!("{}", pretty(&json!({"dry_run": dry_run, "results": results})));
                return Ok(0);
            }
            for row in &results {
                let action = if dry_run { "would drop" } else { "dropped" };
                println!(
                    "{}: {action} {}, kept {}",
                    row["ref"].as_str().unwrap(),
                    row["dropped"],
                    row["kept"]
                );
            }
            if dry_run {
                println!("dry run: nothing was changed");
            }
            Ok(0)
        }
        Cmd::CountObjects { json } => {
            let repo = open_repo(&cli.repo)?;
            let result = count_objects(&repo)?;
            if json {
                println!("{}", pretty(&result));
                return Ok(0);
            }
            let types: Vec<String> = result["by_type"]
                .as_object()
                .unwrap()
                .iter()
                .filter(|(_t, n)| n.as_u64().unwrap_or(0) > 0)
                .map(|(t, n)| format!("{t} {n}"))
                .collect();
            println!(
                "objects:  {} loose ({}), {} corrupt",
                result["loose_objects"],
                if types.is_empty() { "none".to_owned() } else { types.join(", ") },
                result["corrupt_objects"]
            );
            println!("disk:     {} bytes", result["disk_bytes"]);
            println!("refs:     {} heads, {} anchors", result["heads"], result["anchors"]);
            println!("reflog:   {} entries, {} bytes", result["reflog_entries"], result["reflog_bytes"]);
            println!("tmp:      {} stale files", result["tmp_files"]);
            for warning in result["warnings"].as_array().unwrap() {
                println!("warning: {}", warning.as_str().unwrap());
            }
            Ok(0)
        }
        Cmd::Verify { json } => {
            let repo = open_repo(&cli.repo)?;
            let findings = verify_repository(&repo);
            if json {
                println!("{}", pretty(&json!(findings)));
            } else {
                for finding in &findings {
                    println!(
                        "{}: [{}] {}",
                        finding["severity"].as_str().unwrap(),
                        finding["code"].as_str().unwrap(),
                        finding["message"].as_str().unwrap()
                    );
                }
            }
            let errors = findings.iter().filter(|f| f["severity"].as_str() == Some("error")).count();
            if errors > 0 {
                println!("verify: {errors} error(s) detected");
                return Ok(3);
            }
            if !json {
                let note = if findings.is_empty() {
                    String::new()
                } else {
                    format!(" ({} warning(s))", findings.len())
                };
                println!("verify: repository is healthy{note}");
            }
            Ok(0)
        }
        Cmd::Anchor { name, thought_id, author, timestamp, json } => {
            let repo = open_repo(&cli.repo)?;
            match name {
                None => {
                    let anchors = repo.list_anchors()?;
                    if json {
                        println!("{}", pretty(&json!(anchors)));
                    } else {
                        for anchor in anchors {
                            println!(
                                "{} -> {} (anchor {})",
                                anchor["name"].as_str().unwrap(),
                                short(anchor["target"].as_str().unwrap()),
                                short(anchor["anchor"].as_str().unwrap())
                            );
                        }
                    }
                }
                Some(name) => {
                    let thought = thought_id
                        .ok_or_else(|| CoreError::User("anchor: usage `cogit anchor <name> <thought-id>`".into()))?;
                    let oid = repo.anchor(&name, &thought, &author, timestamp.as_deref())?;
                    if json {
                        println!("{}", json!({"name": name, "anchor": oid}));
                    } else {
                        println!("anchor {name} {oid}");
                    }
                }
            }
            Ok(0)
        }
    }
}

fn main() {
    let cli = Cli::parse();
    match run(cli) {
        Ok(code) => std::process::exit(code),
        Err(err) => {
            eprintln!("cogit: {err}");
            std::process::exit(err.exit_code());
        }
    }
}
