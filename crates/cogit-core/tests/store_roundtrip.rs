//! Store behavior parity with prototype/tests/test_store.py.

use serde_json::{json, Value};

use cogit_core::store::ObjectStore;
use cogit_core::CoreError;

fn claim() -> Value {
    json!({
        "type": "claim",
        "kind": "agent_decision",
        "subject": "test",
        "predicate": "store-test",
        "object": "yes",
        "qualifiers": {}
    })
}

fn store() -> (tempfile::TempDir, ObjectStore) {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = ObjectStore::new(dir.path());
    (dir, store)
}

#[test]
fn roundtrip_and_dedup() {
    let (_dir, store) = store();
    let oid1 = store.write(&claim()).unwrap();
    let oid2 = store.write(&claim()).unwrap();
    assert_eq!(oid1, oid2);
    let read = store.read(&oid1).unwrap();
    assert_eq!(read["predicate"], "store-test");
}

#[test]
fn float_and_malformed_rejected_before_write() {
    let (_dir, store) = store();
    let mut with_float = claim();
    with_float["qualifiers"]["confidence"] = json!(0.92);
    assert!(matches!(store.write(&with_float), Err(CoreError::User(_))));
    let unknown_field = json!({"type": "claim", "kind": "nope"});
    assert!(matches!(store.write(&unknown_field), Err(CoreError::User(_))));
}

#[test]
fn corrupt_zlib_body_detected() {
    let (_dir, store) = store();
    let oid = store.write(&claim()).unwrap();
    std::fs::write(store.path_for(&oid).unwrap(), b"not zlib at all").unwrap();
    assert!(matches!(store.read(&oid), Err(CoreError::Corruption(_))));
}

#[test]
fn hash_path_mismatch_detected() {
    let (_dir, store) = store();
    let oid = store.write(&claim()).unwrap();
    let wrong = format!("sha256:{}", "f".repeat(64));
    let wrong_path = store.path_for(&wrong).unwrap();
    std::fs::create_dir_all(wrong_path.parent().unwrap()).unwrap();
    std::fs::rename(store.path_for(&oid).unwrap(), &wrong_path).unwrap();
    assert!(matches!(store.read(&wrong), Err(CoreError::Corruption(_))));
}

#[test]
fn same_path_different_content_collision_detected() {
    let (_dir, store) = store();
    let oid = store.write(&claim()).unwrap();
    // overwrite with a VALID zlib body that is different content
    let bogus = {
        use flate2::write::ZlibEncoder;
        use flate2::Compression;
        use std::io::Write;
        let mut enc = ZlibEncoder::new(Vec::new(), Compression::default());
        enc.write_all(b"claim 2\x00{}").unwrap();
        enc.finish().unwrap()
    };
    std::fs::write(store.path_for(&oid).unwrap(), bogus).unwrap();
    assert!(matches!(store.write(&claim()), Err(CoreError::Corruption(_))));
}
