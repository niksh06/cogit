#!/bin/sh
# Python <-> Rust interoperability proof for COG-013.
#
# Both implementations drive ONE repository, alternating per step; each
# side must read, verify, and extend what the other wrote. Run from the
# repo root:  sh tools/interop-test.sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYBIN="${PYBIN:-$ROOT/.venv/bin/python}"
export PYTHONPATH="$ROOT/prototype"
PY="$PYBIN -m cogit"
RUST="$ROOT/target/debug/cogit"

command -v "$RUST" >/dev/null 2>&1 || cargo build --quiet --manifest-path "$ROOT/Cargo.toml"

WORK="$(mktemp -d /tmp/cogit-interop.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

fail() { echo "INTEROP FAIL: $1" >&2; exit 1; }
step()  { printf ' %-58s' "$1"; }
ok()    { echo "ok"; }

TS1=2026-07-02T20:00:01Z; TS2=2026-07-02T20:00:02Z; TS3=2026-07-02T20:00:03Z
TS4=2026-07-02T20:00:04Z; TS5=2026-07-02T20:00:05Z; TS6=2026-07-02T20:00:06Z
TS7=2026-07-02T20:00:07Z; TS8=2026-07-02T20:00:08Z

step "python init, rust status reads it"
$PY init . >/dev/null
$RUST status --json | grep -q '"branch": "main"' || fail "rust cannot read python init"
ok

step "python micro-commit, rust blames the fact"
OUT=$($PY add-fact --kind agent_decision --subject interop --predicate first \
  --object yes --source agent:interop --confidence 9000 --actor py \
  --asserted-at $TS1 --commit --timestamp $TS1 --json)
A1=$(echo "$OUT" | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["assertion"])')
T1=$(echo "$OUT" | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["thought"])')
$RUST blame-fact "$A1" --json | grep -q "$T1" || fail "rust blame disagrees"
ok

step "rust commits on a rust-made branch, python logs both"
$RUST branch side --timestamp $TS2 >/dev/null
$RUST checkout side --timestamp $TS2 >/dev/null
OUT=$($RUST add-fact --kind agent_decision --subject interop --predicate second \
  --object yes --source agent:interop --confidence 8000 --actor rs \
  --asserted-at $TS3 --commit --timestamp $TS3 --json)
A2=$(echo "$OUT" | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["assertion"])')
T2=$(echo "$OUT" | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["thought"])')
$PY log --json | grep -q "$T2" || fail "python cannot walk rust commit"
ok

step "identical fact content -> identical object IDs across runtimes"
PYID=$($PY hash-object --type claim "{\"type\":\"claim\",\"kind\":\"tool_observation\",\"subject\":\"x\",\"predicate\":\"p\",\"object\":\"жест\",\"qualifiers\":{\"n\":1}}")
RSID=$($RUST hash-object --type claim "{\"type\":\"claim\",\"kind\":\"tool_observation\",\"subject\":\"x\",\"predicate\":\"p\",\"object\":\"жест\",\"qualifiers\":{\"n\":1}}")
[ "$PYID" = "$RSID" ] || fail "object ids differ: $PYID vs $RSID"
ok

step "conflicting merge: rust merges, python sees the same conflict"
$RUST checkout main --timestamp $TS4 >/dev/null
$PY add-fact --kind agent_decision --subject interop --predicate second \
  --object yes --source agent:interop --confidence 1000 --actor py \
  --asserted-at $TS4 >/dev/null
$PY commit-thought -m "rival view" --author py --timestamp $TS5 >/dev/null
$RUST merge side --timestamp $TS6 >/dev/null 2>&1 && fail "merge should conflict"
CLAIM=$($PY status --json | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["conflicts"][0]["claim"])')
[ -n "$CLAIM" ] || fail "python does not see rust conflict"
ok

step "python resolves, rerere fingerprints match, rust commits the merge"
$PY resolve "$CLAIM" --keep "$A2" >/dev/null
PYFP=$($PY rerere --json | $PYBIN -c 'import json,sys; print(next(iter(json.load(sys.stdin))))')
RSFP=$($RUST rerere --json | $PYBIN -c 'import json,sys; print(next(iter(json.load(sys.stdin))))')
[ "$PYFP" = "$RSFP" ] || fail "rerere fingerprints diverge: $PYFP vs $RSFP"
MERGE=$($RUST commit-thought -m "merge side" --author rs --timestamp $TS7 --json | $PYBIN -c 'import json,sys; print(json.load(sys.stdin)["thought"])')
ok

step "annotations round-trip (rust writes, python lists)"
$RUST annotate "$MERGE" -m "interop reviewed" --namespace audit --author rs --timestamp $TS8 >/dev/null
$PY annotations "$MERGE" --json | grep -q "interop reviewed" || fail "python cannot read rust annotation"
ok

step "recap agrees across runtimes"
PYR=$($PY recap "$T1" --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(len(d["thoughts"]), len(d["added"]))')
RSR=$($RUST recap "$T1" --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(len(d["thoughts"]), len(d["added"]))')
[ "$PYR" = "$RSR" ] || fail "recap disagrees: $PYR vs $RSR"
ok

step "both verifiers call the shared repository healthy"
$PY verify >/dev/null || fail "python verify failed"
$RUST verify >/dev/null || fail "rust verify failed"
ok

step "cross-check: rust count-objects equals python count-objects"
PYC=$($PY count-objects --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(d["loose_objects"], d["reflog_entries"])')
RSC=$($RUST count-objects --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(d["loose_objects"], d["reflog_entries"])')
[ "$PYC" = "$RSC" ] || fail "metrics disagree: $PYC vs $RSC"
ok

step "micro-commits: rust writes with project, python filters find it"
$RUST add-fact --kind agent_decision --subject interop:micro --predicate landed \
  --object yes --source agent:interop --confidence 9000 --actor rs \
  --asserted-at $TS8 --project interop --commit --timestamp $TS8 >/dev/null
COUNT=$($PY facts --project interop --json | $PYBIN -c 'import json,sys; print(len(json.load(sys.stdin)["facts"]))')
[ "$COUNT" = "1" ] || fail "python project filter sees $COUNT facts"
COUNT=$($RUST facts --subject 'interop:*' --json | $PYBIN -c 'import json,sys; print(len(json.load(sys.stdin)["facts"]))')
[ "$COUNT" = "1" ] || fail "rust subject filter sees $COUNT facts"
ok

step "no-arg recap agrees and reports the anchor"
$PY anchor interop-done HEAD --timestamp $TS8 >/dev/null
PYR=$($PY recap --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(d["from_anchor"], d["same_point"])')
RSR=$($RUST recap --json | $PYBIN -c 'import json,sys; d=json.load(sys.stdin); print(d["from_anchor"], d["same_point"])')
[ "$PYR" = "$RSR" ] || fail "no-arg recap disagrees: $PYR vs $RSR"
ok

echo "INTEROP OK: Python and Rust drive one repository interchangeably"
