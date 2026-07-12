# Object Format v1

created_datetime: 2026-05-26T21:40:00+03:00
updated_datetime: 2026-07-02T12:00:00+03:00
status: Draft

## Purpose

This document defines the MVP Cogit object format. Implementations must follow this contract to preserve stable object IDs across runtimes.

## Object Identity

Object IDs are SHA-256 hashes of the uncompressed object preimage:

```text
<type> <size>\0<canonical-json>
```

Where:

- `<type>` is one of `claim`, `assertion`, `mindset`, `thought`, `anchor`,
  `annotation` (the last added by ADR-0012).
- `<size>` is the byte length of `<canonical-json>` encoded as UTF-8.
- `\0` is a single NUL byte.
- `<canonical-json>` is UTF-8 JSON following the canonicalization rules below.

The stored body is `zlib(preimage)`.

## Storage Path

The object ID is 64 lowercase hexadecimal characters.

The storage path is:

```text
.cogit/objects/<first-2-hex>/<remaining-62-hex>
```

Example:

```text
.cogit/objects/ab/cdef...
```

## Canonical JSON

Canonical JSON rules (a JCS-inspired profile; see ADR-0010):

- UTF-8 encoding, no BOM.
- Object keys sorted by Unicode code point (equivalently: by UTF-8 byte
  order). This differs from RFC 8785's UTF-16 ordering only for keys with
  non-BMP characters; schema-defined keys are ASCII.
- No insignificant whitespace.
- String escaping is minimal and deterministic: `\"` and `\\`; control
  characters U+0000..U+001F use `\b`, `\t`, `\n`, `\f`, `\r` where defined
  and lowercase `\u00xx` otherwise. All other characters, including
  non-ASCII, are emitted as raw UTF-8 without escaping.
- Numbers are integers only, with magnitude at most 2^53 - 1, no leading
  zeros, no plus sign, no exponent notation.
- Timestamps are ISO-8601 UTC strings with `Z` suffix.
- Hash references include an explicit `sha256:` prefix in JSON values.
- Lists that represent sets must be sorted lexicographically unless the field explicitly preserves order.
- Floating-point values are forbidden in MVP objects.
- Confidence is encoded as an integer basis point value from `0` to `10000`, not as a float.
- Unknown fields are rejected unless an object schema explicitly allows extension metadata.

Rationale: different JSON encoders must not produce different object IDs for the same logical object.

## Object Schemas

### Claim

Required fields:

```json
{
  "type": "claim",
  "kind": "user_preference",
  "subject": "user",
  "predicate": "prefers_response_style",
  "object": "brief",
  "qualifiers": {
    "scope": "assistant_reply"
  }
}
```

Rules:

- `type` must be `claim`.
- `kind` is one of `user_preference`, `tool_observation`, `document_claim`, `agent_decision`, `policy_constraint`.
- `subject`, `predicate`, and `object` are required.
- `qualifiers` is an object and may be empty.
- A negated claim uses `negates: "sha256:<claim-id>"`.

### Assertion

Required fields:

```json
{
  "type": "assertion",
  "claim": "sha256:...",
  "status": "asserted",
  "source": {
    "type": "prompt",
    "uri": "conversation:current"
  },
  "confidence_bps": 9200,
  "asserted_at": "2026-05-26T18:00:00Z",
  "actor": "agent",
  "method": {
    "type": "user_statement"
  }
}
```

Optional fields:

- `premises`: a non-empty, sorted, deduplicated array of assertion IDs
  this belief derives from (ADR-0013). Absent means "no recorded
  premises"; every referenced assertion must already exist at write
  time, which makes the derivation graph acyclic by construction.
  Premises are part of the identity preimage: the same claim derived
  from different evidence is a different assertion.

Rules:

- `type` must be `assertion`.
- `claim` references a `claim` object.
- `status` is one of `asserted`, `refuted`, `superseded`.
- `source.type` is one of `prompt`, `tool`, `file`, `url`, `system`, `manual`, `agent`.
- `confidence_bps` is an integer from `0` to `10000`.
- `asserted_at` is required.
- `actor` is a non-empty string in MVP.
- `method` is an object.
- `premises`, when present, follows the optional-field rules above.

### Mindset

Required fields:

```json
{
  "type": "mindset",
  "assertions": ["sha256:..."],
  "created_at": "2026-05-26T18:01:00Z"
}
```

Rules:

- `assertions` is a lexicographically sorted list of unique assertion IDs.
- Every ID must reference an existing `assertion` object for `verify` to pass.

### Thought

Required fields:

```json
{
  "type": "thought",
  "parents": ["sha256:..."],
  "mindset": "sha256:...",
  "operation": "commit",
  "message": "Captured user's output preference.",
  "author": "agent",
  "timestamp": "2026-05-26T18:02:00Z"
}
```

Rules:

- `parents` is a list of unique thought IDs in semantic order; it is exempt
  from set-sorting because order is meaningful (decided per CQ-006).
- For merge thoughts, `parents[0]` is current/ours and `parents[1]` is merged/theirs.
- The first thought uses an empty `parents` list.
- `mindset` references a `mindset` object.
- `operation` is one of `commit`, `merge`, `checkout`, `anchor`, `import`, `repair`.
- `message` is non-empty.
- `author` is non-empty.
- `timestamp` is required.
- OPTIONAL `removals` (ADR-0014, additive): non-empty list of
  `{"assertion": "sha256:...", "reason": "<non-empty>"}`, sorted by
  `assertion`, unique — the durable record of WHY each assertion left the
  mindset in this thought. Absent field ≡ no recorded reasons (all
  pre-ADR objects stay valid). The field is part of the preimage
  (identity-bearing). `verify` cross-checks entries against the actual
  parent-to-mindset delta.
- OPTIONAL `writer` (ADR-0016, additive): the build that wrote this
  thought, a single token `<impl>/<version>` (e.g. `cogit-py/0.3.0`;
  an optional `+<build>` suffix on the version is reserved). At most 64
  characters, no whitespace or control characters, exactly one `/`,
  both halves non-empty. Absent field ≡ pre-0.3.0 writer (the entire
  earlier history stays valid). Thoughts ONLY: claims and assertions
  are identity-deduplicated across writers and MUST NOT carry a
  version, or identical facts would split into different IDs.

### Anchor

Required fields:

```json
{
  "type": "anchor",
  "name": "plan-approved",
  "target": "sha256:...",
  "created_at": "2026-05-26T18:03:00Z",
  "author": "agent"
}
```

Rules:

- `name` must be a valid ref segment.
- `target` references a `thought` object.
- Anchor objects do not rewrite target thoughts.

### Annotation

Required fields (ADR-0012):

```json
{
  "type": "annotation",
  "target": "sha256:...",
  "namespace": "audit",
  "body": "Root cause confirmed by regression test.",
  "author": "reviewer",
  "created_at": "2026-07-02T16:00:00Z",
  "parents": []
}
```

Rules:

- `target` references a `thought`, `assertion`, or `claim` object.
- `namespace` is a single valid ref segment.
- `body` and `author` are non-empty strings.
- `parents` is a list of unique annotation IDs in chain order (the previous
  namespace tip, or empty for the first annotation); exempt from
  set-sorting because order is meaningful.
- Annotations never rewrite their targets.

## Read Rules

An implementation reading an object must:

1. Locate the object path from the object ID.
2. Decompress zlib body.
3. Parse header and JSON after NUL.
4. Verify declared size.
5. Recompute SHA-256 over the full preimage.
6. Compare computed hash with requested object ID.
7. Validate schema.

Any failure is a read error and must be reported by `verify`.

## Write Rules

An implementation writing an object must:

1. Validate object schema.
2. Produce canonical JSON.
3. Build preimage.
4. Compute SHA-256.
5. Write compressed preimage to a temporary file.
6. Atomically publish to the fanout path.
7. If target path exists, verify existing content matches the same preimage.
8. Reject same-path, different-content collisions.

## Invariants

- Object content never changes after publication.
- Object ID is derived only from object preimage bytes.
- Same canonical bytes always produce the same object ID.
- Same semantic claim with different canonical bytes is not automatically the same claim.
- All object references are explicit `sha256:` strings.

## Test Vectors

Frozen test vectors live in `prototype/vectors/object-vectors-v1.json`, one
per object type. Each vector includes:

- input object JSON;
- canonical JSON string;
- preimage bytes as escaped text;
- SHA-256 object ID.

Any implementation must reproduce these object IDs byte-for-byte. Vectors
change only through an explicit ADR. Stored zlib bodies are validated by
round-trip decompression, not by byte equality, because compressed bytes may
legally differ across zlib settings while the preimage and ID stay fixed.
