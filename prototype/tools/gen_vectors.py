"""Generate frozen object-format test vectors (OQ-003 / CQ-011).

Run from prototype/:  python3 tools/gen_vectors.py
Vectors freeze object identity: any implementation must reproduce these IDs.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cogit.canonical import canonical_json  # noqa: E402
from cogit.objects import encode_object  # noqa: E402

TS = "2026-07-02T10:00:00Z"


def build_chain():
    claim = {
        "type": "claim",
        "kind": "user_preference",
        "subject": "user",
        "predicate": "prefers_response_style",
        "object": "brief",
        "qualifiers": {"scope": "assistant_reply"},
    }
    claim_id, _ = encode_object(claim)

    assertion = {
        "type": "assertion",
        "claim": claim_id,
        "status": "asserted",
        "source": {"type": "prompt", "uri": "conversation:current"},
        "confidence_bps": 9200,
        "asserted_at": TS,
        "actor": "agent",
        "method": {"type": "user_statement"},
    }
    assertion_id, _ = encode_object(assertion)

    mindset = {"type": "mindset", "assertions": [assertion_id], "created_at": TS}
    mindset_id, _ = encode_object(mindset)

    thought = {
        "type": "thought",
        "parents": [],
        "mindset": mindset_id,
        "operation": "commit",
        "message": "Captured user's output preference.",
        "author": "agent",
        "timestamp": TS,
    }
    thought_id, _ = encode_object(thought)

    anchor = {
        "type": "anchor",
        "name": "plan-approved",
        "target": thought_id,
        "created_at": TS,
        "author": "agent",
    }
    return [claim, assertion, mindset, thought, anchor]


def main():
    vectors = []
    for obj in build_chain():
        oid, preimage = encode_object(obj)
        vectors.append(
            {
                "type": obj["type"],
                "object": obj,
                "canonical_json": canonical_json(obj),
                "preimage": preimage.decode("utf-8"),
                "object_id": oid,
            }
        )
    out_path = os.path.join(os.path.dirname(__file__), "..", "vectors", "object-vectors-v1.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({"format": "object-format-v1", "vectors": vectors}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {len(vectors)} vectors to {os.path.normpath(out_path)}")


if __name__ == "__main__":
    main()
