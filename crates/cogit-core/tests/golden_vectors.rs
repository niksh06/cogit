//! The Rust port MUST reproduce the frozen vectors byte-for-byte (ADR-0010).

use serde_json::Value;

use cogit_core::canonical::canonical_json;
use cogit_core::objects::encode_object;

fn load_vectors() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../prototype/vectors/object-vectors-v1.json"
    );
    let text = std::fs::read_to_string(path).expect("vectors file");
    let doc: Value = serde_json::from_str(&text).expect("vectors json");
    doc["vectors"].as_array().expect("vectors array").clone()
}

#[test]
fn all_types_present() {
    let types: Vec<String> = load_vectors()
        .iter()
        .map(|v| v["type"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(
        types,
        // the trailing assertion is the additive premises vector (ADR-0013)
        ["claim", "assertion", "mindset", "thought", "anchor", "annotation", "assertion"]
    );
}

#[test]
fn vectors_reproduce_byte_for_byte() {
    for vector in load_vectors() {
        let object = &vector["object"];
        let expected_canonical = vector["canonical_json"].as_str().unwrap();
        let expected_preimage = vector["preimage"].as_str().unwrap();
        let expected_oid = vector["object_id"].as_str().unwrap();

        let canonical = canonical_json(object).expect("canonicalize");
        assert_eq!(canonical, expected_canonical, "canonical json for {}", vector["type"]);

        let (oid, preimage) = encode_object(object).expect("encode");
        assert_eq!(
            preimage,
            expected_preimage.as_bytes(),
            "preimage for {}",
            vector["type"]
        );
        assert_eq!(oid, expected_oid, "object id for {}", vector["type"]);
    }
}
