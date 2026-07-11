# ADR-0015: Tolerant Readers (Forward-Compatible Reads)

created_datetime: 2026-07-11T00:40:00+03:00
status: Accepted (field incident 2026-07-10)

## Context

ADR-0013 (premises) and ADR-0014 (removals) extended the object format
"additively": old objects stay valid, frozen vectors intact. But our
readers validated the FULL schema strictly on every read — unknown
fields were rejected. The result in the field, within a day of shipping
ADR-0014: a long-running session (its MCP server holds code from process
start) read a thought that a freshly-spawned hook had written with
`removals` and died with `CorruptionError: unknown fields: ['removals']`.
"Additive" was only additive for writers.

Git solved this decades ago: readers parse the commit headers they know
and preserve the ones they don't — which is exactly how `gpgsig` and
friends were introduced without breaking a single old client.

## Decision

1. **Reads are tolerant of unknown fields on known types.**
   `validate_object(obj, mode="read")` (Python) /
   `validate_object_read` (Rust) skip only the unknown-field rejection;
   every other check still runs — required fields, value shapes, sorted
   premises/removals, and above all the content hash and canonical-bytes
   round-trip, which guarantee byte integrity regardless of schema
   knowledge. Unknown OBJECT TYPES remain fatal (a reader cannot reason
   about an object whose semantics it has no notion of).
2. **Writes stay strict.** `ObjectStore.write` validates in write mode:
   this implementation never writes a field it does not understand.
3. **Skew is visible, not silent.** `verify` re-validates strictly and
   reports objects with unknown fields as a WARNING (`unknown-fields`,
   "written by a newer version?") — operators see the version skew
   without any reader breaking.
4. **Definition updated**: from now on, "additive format extension"
   MEANS both sides — old objects validate under new code AND new
   objects load under old-but-tolerant code. ADR-0013/0014 fields are
   grandfathered: readers older than this ADR still reject them; the
   only cure there is restarting the stale process.

## Consequences

- Future additive fields (e.g. COG-064 detail-annotations) cannot break
  a deployed reader again.
- A tolerant read preserves unknown fields verbatim (parse → canonical
  re-encode must reproduce the exact bytes), so hashing, copying and
  re-serving newer objects through older code is loss-free.
- The invariant "reads verify hash and schema" is refined: reads verify
  hash and the KNOWN-field schema; full-schema strictness is a write-side
  and verify-side property.
