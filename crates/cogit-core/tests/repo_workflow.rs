//! End-to-end repository workflow: the PRD acceptance scenario plus the
//! conflict/blame/verify paths, mirroring prototype/tests/test_repo.py.

use serde_json::{json, Value};

use cogit_core::repo::{init_repository, Repository};
use cogit_core::verify::verify_repository;
use cogit_core::CoreError;

fn ts(n: u64) -> String {
    format!("2026-07-02T10:{:02}:{:02}Z", n / 60, n % 60)
}

fn fact_doc(predicate: &str, confidence: i64) -> Value {
    json!({
        "claim": {
            "type": "claim",
            "kind": "agent_decision",
            "subject": "test",
            "predicate": predicate,
            "object": "yes",
            "qualifiers": {},
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "manual", "uri": "test:fixture"},
            "confidence_bps": confidence,
            "asserted_at": "2026-07-02T10:00:00Z",
            "actor": "tester",
            "method": {"type": "fixture"},
        },
    })
}

fn make_repo() -> (tempfile::TempDir, Repository) {
    let dir = tempfile::tempdir().expect("tempdir");
    init_repository(dir.path()).expect("init");
    let repo = Repository::open(dir.path()).expect("open");
    (dir, repo)
}

#[test]
fn prd_acceptance_scenario() {
    let (_dir, repo) = make_repo();
    let (_c1, a1) = repo.add_fact(&fact_doc("first", 9000)).unwrap();
    let (_c2, _a2) = repo.add_fact(&fact_doc("second", 9000)).unwrap();
    let t1 = repo.commit_thought("two facts", "agent", Some(&ts(1))).unwrap();

    repo.branch("hypothesis-a", None, "agent", Some(&ts(2))).unwrap();
    repo.checkout("hypothesis-a", "agent", Some(&ts(3))).unwrap();
    let (_c3, a3) = repo.add_fact(&fact_doc("alternative", 9000)).unwrap();
    let t2 = repo.commit_thought("alternative view", "agent", Some(&ts(4))).unwrap();

    repo.checkout("main", "agent", Some(&ts(5))).unwrap();
    let status = repo.status().unwrap();
    assert_eq!(status["branch"], "main");
    assert_eq!(status["thought"].as_str(), Some(t1.as_str()));

    // identical fact content -> identical id (staged again, then cleaned)
    let (_c, a1_again) = repo.add_fact(&fact_doc("first", 9000)).unwrap();
    assert_eq!(a1, a1_again);
    repo.remove_fact(&a1_again, "test-cleanup").unwrap();

    let diff = repo.diff(&t1, &t2).unwrap();
    assert_eq!(diff["added"], json!([a3]));
    assert_eq!(diff["removed"], json!([]));

    let blame = repo.blame_fact(&a3, Some(&t2)).unwrap();
    assert_eq!(blame["thought"].as_str(), Some(t2.as_str()));

    assert!(repo.reflog("HEAD").unwrap().len() >= 4);
}

#[test]
fn conflicting_merge_blocks_commit_until_resolved() {
    let (_dir, repo) = make_repo();
    repo.add_fact(&fact_doc("base", 9000)).unwrap();
    repo.commit_thought("base", "agent", Some(&ts(0))).unwrap();
    repo.branch("side", None, "agent", Some(&ts(1))).unwrap();
    let (_c, a_main) = repo.add_fact(&fact_doc("disputed", 9000)).unwrap();
    repo.commit_thought("main view", "agent", Some(&ts(2))).unwrap();
    repo.checkout("side", "agent", Some(&ts(3))).unwrap();
    let (_c, a_side) = repo.add_fact(&fact_doc("disputed", 1000)).unwrap();
    repo.commit_thought("side view", "agent", Some(&ts(4))).unwrap();
    repo.checkout("main", "agent", Some(&ts(5))).unwrap();

    let result = repo.merge("side", "agent", Some(&ts(6))).unwrap();
    assert_eq!(result["result"], "conflicts");
    let conflict = &result["conflicts"][0];
    assert_eq!(conflict["ours"], json!([a_main]));
    assert_eq!(conflict["theirs"], json!([a_side]));

    // conflict blocks commit — merge never silently drops facts
    assert!(matches!(
        repo.commit_thought("premature", "agent", Some(&ts(7))),
        Err(CoreError::User(_))
    ));

    let claim = conflict["claim"].as_str().unwrap();
    repo.resolve_conflict(claim, Some(&a_side), false, false).unwrap();
    let merge_thought = repo.commit_thought("merge resolved", "agent", Some(&ts(8))).unwrap();
    let mindset = repo.mindset_assertions(Some(&merge_thought)).unwrap();
    assert!(mindset.contains(&a_side));
    assert!(!mindset.contains(&a_main));

    // rerere remembered the arbitration
    let store = cogit_core::rerere::load_rerere(&repo.cogit_dir);
    assert_eq!(store.len(), 1);

    // healthy end state (the abandoned rival line is dangling: warnings allowed)
    let findings = verify_repository(&repo);
    assert!(findings.iter().all(|f| f["severity"] == "warning"), "{findings:?}");
}

#[test]
fn contradictory_commit_rejected_then_refute_flow() {
    let (_dir, repo) = make_repo();
    let (claim_oid, a0) = repo.add_fact(&fact_doc("belief", 9000)).unwrap();
    repo.commit_thought("believe", "agent", Some(&ts(0))).unwrap();

    let mut neg = fact_doc("belief", 9500);
    neg["claim"]["object"] = json!(false);
    neg["claim"]["negates"] = json!(claim_oid);
    repo.add_fact(&neg).unwrap();
    assert!(matches!(
        repo.commit_thought("contradiction", "agent", Some(&ts(1))),
        Err(CoreError::User(_))
    ));
    repo.remove_fact(&a0, "refuted").unwrap();
    let t2 = repo.commit_thought("refute", "agent", Some(&ts(2))).unwrap();
    assert_eq!(repo.mindset_assertions(Some(&t2)).unwrap().len(), 1);

    // COG-040: the surviving row is flagged as a negation
    let facts = repo.facts(None, None, None, None).unwrap();
    let rows = facts["facts"].as_array().unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["negation"], json!(true));
    assert_eq!(rows[0]["negates"], json!(claim_oid));
}

#[test]
fn secret_guard_allows_paths_rejects_tokens() {
    use cogit_core::secrets::reject_suspected_secrets;
    // COG-048: the exact live-failure string must be accepted
    let path = json!(
        "~/Reports/projects/aleph/reference/cogit-claim-modeling-memo-2026-07-05.md");
    assert!(reject_suspected_secrets(&path, "test").is_ok());
    let code_path = json!("/Users/nsh/Downloads/cogit/prototype/integrations/mcp_server.py");
    assert!(reject_suspected_secrets(&code_path, "test").is_ok());
    // slash-bearing random material must STILL be rejected
    let token = json!("token aB3dEf/Gh1jKl/Mn0pQr/xY2zAb/Cd4eFg9");
    assert!(matches!(reject_suspected_secrets(&token, "test"), Err(CoreError::User(_))));
}

#[test]
fn premises_validate_and_round_trip() {
    let (_dir, repo) = make_repo();
    let (claim_oid, evidence) = repo.add_fact(&fact_doc("evidence", 9900)).unwrap();
    repo.commit_thought("evidence", "agent", Some(&ts(0))).unwrap();

    let mut derived = fact_doc("conclusion", 8200);
    derived["assertion"]["premises"] = json!([evidence.clone()]);
    let (_c, derived_aid) = repo.add_fact(&derived).unwrap();
    repo.commit_thought("derived", "agent", Some(&ts(1))).unwrap();
    let facts = repo.facts(None, None, None, None).unwrap();
    let row = facts["facts"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["assertion"] == json!(derived_aid))
        .cloned()
        .unwrap();
    assert_eq!(row["premises"], json!([evidence]));
    assert_eq!(row["actor"], json!("tester")); // COG-052: writer exposed in rows

    // a claim id is not an assertion (ADR-0013 write-time check)
    let mut bad = fact_doc("bad", 8000);
    bad["assertion"]["premises"] = json!([claim_oid]);
    assert!(matches!(repo.add_fact(&bad), Err(CoreError::User(_))));

    // shape rules reject non-oid premises
    let mut shape = fact_doc("shape", 8000);
    shape["assertion"]["premises"] = json!(["not-an-oid"]);
    assert!(matches!(repo.add_fact(&shape), Err(CoreError::User(_))));
}

#[test]
fn dump_one_call_surface() {
    let (_dir, repo) = make_repo();
    let (_c1, a1) = repo.add_fact(&fact_doc("alpha", 9000)).unwrap();
    let t1 = repo.commit_thought("first", "agent", Some(&ts(0))).unwrap();
    repo.anchor("base", "HEAD", "agent", Some(&ts(1))).unwrap();
    let (_c2, a2) = repo.add_fact(&fact_doc("beta", 9000)).unwrap();
    let t2 = repo.commit_thought("second", "agent", Some(&ts(2))).unwrap();

    let doc = repo.dump(None, None, None, 50).unwrap();
    assert_eq!(doc["thought"], json!(t2));
    assert_eq!(doc["facts"].as_array().unwrap().len(), 2);
    assert_eq!(doc["introducer"][a1.as_str()], json!(t1));
    assert_eq!(doc["introducer"][a2.as_str()], json!(t2));
    assert_eq!(doc["recap"]["from_anchor"], json!("base"));
    assert_eq!(doc["log"].as_array().unwrap().len(), 2);

    let limited = repo.dump(None, None, None, 1).unwrap();
    assert_eq!(limited["log"].as_array().unwrap().len(), 1);
}

#[test]
fn parallel_micro_commits_all_land() {
    let dir = tempfile::tempdir().expect("tempdir");
    init_repository(dir.path()).expect("init");
    let path = dir.path().to_path_buf();
    let writers = 2;
    let per_writer = 5;
    let handles: Vec<_> = (0..writers)
        .map(|w| {
            let path = path.clone();
            std::thread::spawn(move || {
                let repo = Repository::open(&path).expect("open");
                for n in 0..per_writer {
                    repo.micro_commit(&fact_doc(&format!("w{w}-fact-{n}"), 9000), None, None, None)
                        .expect("micro commit");
                }
            })
        })
        .collect();
    for handle in handles {
        handle.join().expect("writer thread");
    }
    let repo = Repository::open(&path).expect("open");
    let facts = repo.facts(None, None, None, None).expect("facts");
    assert_eq!(facts["facts"].as_array().unwrap().len(), writers * per_writer);
    assert_eq!(repo.log(None).expect("log").len(), writers * per_writer); // linear history
    let errors: Vec<Value> = verify_repository(&repo)
        .into_iter()
        .filter(|f| f["severity"] == "error")
        .collect();
    assert!(errors.is_empty(), "{errors:?}");
}

#[test]
fn micro_commit_noop_and_filters() {
    let (_dir, repo) = make_repo();
    let mut doc = fact_doc("filters", 9000);
    doc["claim"]["qualifiers"] = json!({"project": "alpha"});
    let first = repo.micro_commit(&doc, None, None, Some(&ts(0))).unwrap();
    assert_eq!(first["already_active"], false);
    let again = repo.micro_commit(&doc, None, None, Some(&ts(1))).unwrap();
    assert_eq!(again["already_active"], true);
    assert_eq!(again["thought"], first["thought"]);
    // filters: subject prefix + project qualifier
    let rows = repo.facts(None, Some("test*"), None, Some("alpha")).unwrap();
    assert_eq!(rows["facts"].as_array().unwrap().len(), 1);
    let none = repo.facts(None, None, None, Some("beta")).unwrap();
    assert_eq!(none["facts"].as_array().unwrap().len(), 0);
    // no-arg recap: no anchors -> from root; same_point at the single thought
    let recap = repo.recap(None, None).unwrap();
    assert_eq!(recap["same_point"], true);
    assert_eq!(recap["from_anchor"], Value::Null);
}

#[test]
fn concurrent_ref_update_rejected() {
    let (_dir, repo) = make_repo();
    repo.add_fact(&fact_doc("base", 9000)).unwrap();
    let t1 = repo.commit_thought("first", "agent", Some(&ts(0))).unwrap();
    // simulate a stale writer: wrong expected old target
    let err = repo
        .refs
        .update_ref("refs/heads/main", &t1, None, "other", "commit", "stale", &ts(1))
        .unwrap_err();
    assert!(matches!(err, CoreError::Concurrent(_)));
}
