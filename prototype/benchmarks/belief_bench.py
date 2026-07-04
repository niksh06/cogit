#!/usr/bin/env python3
"""Belief-recovery benchmark (COG-039): journal vs markdown vs transcript.

Generates synthetic-but-realistic working sessions with known ground
truth, records each session into three competing media, and grades
probe answers produced by context-free readers.

    python3 belief_bench.py generate --out DIR [--sessions 4] [--seed 20260704]
    python3 belief_bench.py grade --out DIR --answers ANSWERS_DIR

Media (each written idiomatically — no strawmen):
  journal/    a cogit repository (micro-commits, staged supersede/refute
              with reasons, anchors at milestones; noise skipped)
  markdown/   disciplined agent notes: current-state table updated in
              place + append-only decision log with milestone markers
  transcript/ append-only raw session log, noise included

Probe classes: P1 current value, P2 provenance of current belief,
P3 revision history, P4 delta since last milestone, P5 calibration
(confidence band + basis). Answers are graded mechanically; P4 by F1.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.repo import Repository, init_repository  # noqa: E402

SLOT_POOL = [
    ("api:/orders", "timeout_seconds", [15, 30, 45, 60, 90]),
    ("api:/orders", "returns_status_on_post", [200, 500, 503]),
    ("api:/payments", "rate_limit_rps", [50, 100, 200, 400]),
    ("api:/payments", "idempotency_required", [True, False]),
    ("service:billing", "pool_max_connections", [10, 20, 50, 100]),
    ("service:billing", "owner_team", ["payments-core", "platform", "checkout"]),
    ("service:search", "cache_ttl_seconds", [30, 60, 300, 900]),
    ("service:search", "retries_enabled", [True, False]),
    ("test:orders_suite", "failing_count", [0, 1, 3, 5, 7]),
    ("bug:orders-500", "root_cause", [
        "connection pool exhausted by retry storm",
        "DNS flaps in the service mesh",
        "stale cache after deploy",
        "clock skew between replicas",
    ]),
    ("deploy:orders", "rollout_strategy", ["canary", "blue-green", "all-at-once"]),
    ("user", "prefers_response_style", ["brief", "detailed"]),
]

SOURCES = [
    ("tool", "pytest:run-{n}", "tool_observation", (9800, 10000)),
    ("tool", "grafana:dashboard-{n}", "tool_observation", (9800, 10000)),
    ("prompt", "conversation:review-{n}", "user_preference", (9000, 9600)),
    ("file", "spec/orders-v{n}.md", "document_claim", (8800, 9400)),
    ("agent", "session:debug-{n}", "agent_decision", (5000, 8500)),
]

NOISE = [
    "TOOL bash: ls -la -> 14 entries",
    "HTTP GET /healthz -> 200 in 12ms",
    "TOOL grep: no matches for 'deprecated'",
    "scheduler tick: nothing to do",
    "HTTP GET /metrics -> 200 (4.1 KB)",
]

MEDIA = ("journal", "markdown", "transcript")


def band(confidence_bps):
    if confidence_bps >= 9000:
        return "high"
    if confidence_bps >= 6000:
        return "medium"
    return "low"


def basis(source_type):
    return {"tool": "observation", "prompt": "statement",
            "file": "statement", "agent": "inference"}[source_type]


def ts(i):
    return f"2026-07-04T{10 + i // 60:02d}:{i % 60:02d}:00Z"


def norm(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


# -- event stream -------------------------------------------------------------


def make_source(rng):
    source_type, uri_tpl, kind, (lo, hi) = rng.choice(SOURCES)
    return {
        "source_type": source_type,
        "source_uri": uri_tpl.format(n=rng.randint(1, 99)),
        "kind": kind,
        "confidence": rng.randint(lo // 100, hi // 100) * 100,
    }


def generate_events(rng):
    """Deterministic session shape: assert -> m1 -> churn -> m2 -> churn."""
    slots = rng.sample(SLOT_POOL, 9)
    events, live, i = [], {}, 0

    def emit(op, slot_idx=None, value=None, **extra):
        nonlocal i
        ev = {"op": op, "i": i}
        if slot_idx is not None:
            subject, predicate, _pool = slots[slot_idx]
            ev.update({"subject": subject, "predicate": predicate, "value": value})
        ev.update(extra)
        events.append(ev)
        i += 1
        return ev

    def new_value(slot_idx, avoid=None):
        pool = [v for v in slots[slot_idx][2] if v != avoid]
        return rng.choice(pool)

    # phase A: initial beliefs
    for idx in range(6):
        value = new_value(idx)
        emit("assert", idx, value, **make_source(rng))
        live[idx] = value
    emit("milestone", name="m1")

    # phase B: expand + revise
    for idx in range(6, 9):
        value = new_value(idx)
        emit("assert", idx, value, **make_source(rng))
        live[idx] = value
    for idx in (0, 1):
        value = new_value(idx, avoid=live[idx])
        emit("supersede", idx, value, **make_source(rng))
        live[idx] = value
    emit("refute", 2, live[2], **make_source(rng))
    refuted_b = 2
    live.pop(2)
    emit("noise", line=rng.choice(NOISE))
    emit("noise", line=rng.choice(NOISE))
    emit("milestone", name="m2")

    # phase C: churn after the last milestone (P4 material)
    changed_after_m2 = []
    for idx in (3, 6):
        value = new_value(idx, avoid=live[idx])
        emit("supersede", idx, value, **make_source(rng))
        live[idx] = value
        changed_after_m2.append(idx)
    emit("refute", 4, live[4], **make_source(rng))
    refuted_c = 4
    live.pop(4)
    changed_after_m2.append(4)
    emit("noise", line=rng.choice(NOISE))

    meta = {
        "slots": slots,
        "live": live,
        "refuted": [refuted_b, refuted_c],
        "changed_after_m2": changed_after_m2,
    }
    return events, meta


# -- ground truth and probes ---------------------------------------------------


def build_truth_and_probes(events, meta, rng):
    slots = meta["slots"]
    current = {}   # slot idx -> last assert/supersede event
    history = {}   # slot idx -> list of events
    for ev in events:
        if ev["op"] in ("assert", "supersede", "refute"):
            idx = next(k for k, (s, p, _v) in enumerate(slots)
                       if s == ev["subject"] and p == ev["predicate"])
            history.setdefault(idx, []).append(ev)
            if ev["op"] == "refute":
                current.pop(idx, None)
            else:
                current[idx] = ev

    probes, truth = [], {}

    def add(cls, question, expected):
        pid = f"p{len(probes) + 1:02d}"
        probes.append({"id": pid, "class": cls, "question": question})
        truth[pid] = {"class": cls, **expected}

    def slot_name(idx):
        subject, predicate, _pool = slots[idx]
        return subject, predicate

    active = sorted(current)
    superseded = [i for i in active if len(history[i]) > 1]
    stable = [i for i in active if len(history[i]) == 1]

    # P1 current value x3 (prefer revised slots — they punish stale reads)
    p1_slots = (superseded + stable)[:3]
    for idx in p1_slots:
        subject, predicate = slot_name(idx)
        add("P1",
            f'What is the CURRENT believed value for subject "{subject}", '
            f'predicate "{predicate}"? '
            'Answer JSON: {"value": <string|number|boolean>}',
            {"value": current[idx]["value"]})

    # P2 provenance x2
    for idx in (superseded + stable)[:2]:
        subject, predicate = slot_name(idx)
        add("P2",
            f'Which source introduced the CURRENT belief for "{subject}" '
            f'"{predicate}"? '
            'Answer JSON: {"source_type": "...", "source_uri": "..."}',
            {"source_type": current[idx]["source_type"],
             "source_uri": current[idx]["source_uri"]})

    # P3 revision history x3: superseded / refuted / never-existed
    sup_idx = superseded[0]
    subject, predicate = slot_name(sup_idx)
    old = history[sup_idx][-2]["value"] if history[sup_idx][-1]["op"] == "supersede" \
        else history[sup_idx][0]["value"]
    add("P3",
        f'Was the value "{old}" for "{subject}" "{predicate}" ever believed? '
        'If yes, what happened to that belief? Answer JSON: '
        '{"existed": true|false, "outcome": "superseded"|"refuted"|"active"|"never", '
        '"replacement": <value or null>}',
        {"existed": True, "outcome": "superseded",
         "replacement": current[sup_idx]["value"]})

    ref_idx = meta["refuted"][0]
    subject, predicate = slot_name(ref_idx)
    ref_value = history[ref_idx][-1]["value"]
    add("P3",
        f'Was the value "{ref_value}" for "{subject}" "{predicate}" ever believed? '
        'If yes, what happened to that belief? Answer JSON: '
        '{"existed": true|false, "outcome": "superseded"|"refuted"|"active"|"never", '
        '"replacement": <value or null>}',
        {"existed": True, "outcome": "refuted", "replacement": None})

    never_idx = stable[0]
    subject, predicate = slot_name(never_idx)
    never_value = next(v for v in slots[never_idx][2]
                       if all(v != ev["value"] for ev in history[never_idx]))
    add("P3",
        f'Was the value "{never_value}" for "{subject}" "{predicate}" ever believed? '
        'If yes, what happened to that belief? Answer JSON: '
        '{"existed": true|false, "outcome": "superseded"|"refuted"|"active"|"never", '
        '"replacement": <value or null>}',
        {"existed": False, "outcome": "never", "replacement": None})

    # P4 delta since the last milestone x1
    changed = sorted(f"{slots[i][0]} {slots[i][1]}" for i in meta["changed_after_m2"])
    add("P4",
        'Which beliefs changed AFTER milestone "m2" (asserted, superseded or '
        'refuted)? List each as "<subject> <predicate>". '
        'Answer JSON: {"changed": ["<subject> <predicate>", ...]}',
        {"changed": changed})

    # P5 calibration x1
    idx = (stable + superseded)[0]
    subject, predicate = slot_name(idx)
    add("P5",
        f'For the CURRENT belief about "{subject}" "{predicate}": what is its '
        'confidence band (high: >=9000 bps / 90%; medium: 6000-8999; low: <6000) '
        'and its basis (observation = from a tool; statement = from the user or '
        'a document; inference = the agent\'s own conclusion)? '
        'Answer JSON: {"confidence_band": "...", "basis": "..."}',
        {"confidence_band": band(current[idx]["confidence"]),
         "basis": basis(current[idx]["source_type"])})

    return probes, truth


# -- recorders ------------------------------------------------------------------


def fact_doc(ev, negates=None):
    claim = {
        "type": "claim", "kind": ev["kind"], "subject": ev["subject"],
        "predicate": ev["predicate"], "object": ev["value"],
        "qualifiers": {"project": "bench"},
    }
    if negates:
        claim["negates"] = negates
    return {
        "claim": claim,
        "assertion": {
            "type": "assertion", "status": "asserted",
            "source": {"type": ev["source_type"], "uri": ev["source_uri"]},
            "confidence_bps": ev["confidence"], "asserted_at": ts(ev["i"]),
            "actor": "agent", "method": {"type": "benchmark"},
        },
    }


def record_journal(events, out_dir):
    init_repository(out_dir)
    repo = Repository.open(out_dir)
    current, ops = {}, 0
    for ev in events:
        when = ts(ev["i"])
        if ev["op"] == "noise":
            continue  # cookbook Rule 7: not a belief
        if ev["op"] == "milestone":
            repo.anchor(ev["name"], "HEAD", timestamp=when)
            ops += 1
            continue
        key = (ev["subject"], ev["predicate"])
        if ev["op"] == "assert":
            res = repo.micro_commit(
                fact_doc(ev),
                message=f"{ev['kind']}: {ev['subject']} {ev['predicate']} = {ev['value']}",
                timestamp=when)
            current[key] = {"assertion": res["assertion"], "claim": res["claim"]}
            ops += 1
        elif ev["op"] == "supersede":
            claim_oid, assertion_oid = repo.add_fact(fact_doc(ev))
            repo.remove_fact(current[key]["assertion"], "superseded")
            repo.commit_thought(
                f"supersede: {ev['subject']} {ev['predicate']} -> {ev['value']}",
                "agent", timestamp=when)
            current[key] = {"assertion": assertion_oid, "claim": claim_oid}
            ops += 3
        elif ev["op"] == "refute":
            repo.add_fact(fact_doc(ev, negates=current[key]["claim"]))
            repo.remove_fact(current[key]["assertion"], "refuted")
            repo.commit_thought(
                f"refuted: {ev['subject']} {ev['predicate']} = {ev['value']}",
                "agent", timestamp=when)
            current.pop(key)
            ops += 3
    return ops


def record_markdown(events, path):
    current, log, edits = {}, [], 0

    def flush():
        nonlocal edits
        lines = ["# Working notes", "", "## Current state", "",
                 "| subject | predicate | value | source | confidence |",
                 "| --- | --- | --- | --- | --- |"]
        for (subject, predicate), row in sorted(current.items()):
            lines.append(
                f"| {subject} | {predicate} | {row['value']} | "
                f"{row['source']} | {row['confidence']} bps |")
        lines += ["", "## Decision log", ""] + log + [""]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        edits += 1

    for ev in events:
        when = ts(ev["i"])
        if ev["op"] == "noise":
            continue  # a disciplined notekeeper skips tool noise
        if ev["op"] == "milestone":
            log.append(f"- [{when}] milestone **{ev['name']}**")
            flush()
            continue
        key = (ev["subject"], ev["predicate"])
        source = f"{ev['source_type']}:{ev['source_uri']}"
        if ev["op"] == "assert":
            current[key] = {"value": ev["value"], "source": source,
                            "confidence": ev["confidence"]}
            log.append(f"- [{when}] believe {key[0]} {key[1]} = {ev['value']} "
                       f"({source}, {ev['confidence']} bps)")
        elif ev["op"] == "supersede":
            old = current[key]["value"]
            current[key] = {"value": ev["value"], "source": source,
                            "confidence": ev["confidence"]}
            log.append(f"- [{when}] superseded {key[0]} {key[1]}: {old} -> "
                       f"{ev['value']} ({source}, {ev['confidence']} bps)")
        elif ev["op"] == "refute":
            current.pop(key, None)
            log.append(f"- [{when}] refuted {key[0]} {key[1]} = {ev['value']} — "
                       f"no longer believed ({source})")
        flush()
    return edits


def record_transcript(events, path):
    lines = []
    for ev in events:
        when = ts(ev["i"])
        if ev["op"] == "noise":
            lines.append(f"[{when}] {ev['line']}")
        elif ev["op"] == "milestone":
            lines.append(f"[{when}] -- checkpoint {ev['name']} --")
        elif ev["op"] == "assert":
            lines.append(f"[{when}] noted {ev['subject']} {ev['predicate']} = "
                         f"{ev['value']} (source {ev['source_type']}:{ev['source_uri']}, "
                         f"confidence {ev['confidence']} bps)")
        elif ev["op"] == "supersede":
            lines.append(f"[{when}] update: {ev['subject']} {ev['predicate']} is now "
                         f"{ev['value']} (source {ev['source_type']}:{ev['source_uri']}, "
                         f"confidence {ev['confidence']} bps); earlier value no longer holds")
        elif ev["op"] == "refute":
            lines.append(f"[{when}] correction: {ev['subject']} {ev['predicate']} = "
                         f"{ev['value']} turned out to be wrong "
                         f"(source {ev['source_type']}:{ev['source_uri']})")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return len(lines)


# -- generate / grade ------------------------------------------------------------


def generate(out_dir, sessions, seed):
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"seed": seed, "sessions": []}
    for n in range(1, sessions + 1):
        rng = random.Random(seed + n)
        sid = f"s{n:02d}"
        session_dir = os.path.join(out_dir, "media", sid)
        os.makedirs(os.path.join(session_dir), exist_ok=True)
        events, meta = generate_events(rng)
        probes, truth = build_truth_and_probes(events, meta, rng)

        write_ops = {
            "journal": record_journal(events, os.path.join(session_dir, "journal")),
            "markdown": record_markdown(events, os.path.join(session_dir, "notes.md")),
            "transcript": record_transcript(events, os.path.join(session_dir, "transcript.log")),
        }
        with open(os.path.join(session_dir, "probes.json"), "w", encoding="utf-8") as handle:
            json.dump(probes, handle, indent=2)
        truth_dir = os.path.join(out_dir, "truth")
        os.makedirs(truth_dir, exist_ok=True)
        with open(os.path.join(truth_dir, f"{sid}.json"), "w", encoding="utf-8") as handle:
            json.dump(truth, handle, indent=2)
        manifest["sessions"].append({"id": sid, "events": len(events),
                                     "probes": len(probes), "write_ops": write_ops})
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def _dir_bytes(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return total


def score_answer(cls, expected, answer):
    if not isinstance(answer, dict):
        return 0.0
    if cls == "P1":
        return 1.0 if norm(answer.get("value")) == norm(expected["value"]) else 0.0
    if cls == "P2":
        got_type = norm(answer.get("source_type"))
        got_uri = norm(answer.get("source_uri"))
        return (0.5 * (got_type == norm(expected["source_type"])) +
                0.5 * (got_uri == norm(expected["source_uri"])))
    if cls == "P3":
        existed_ok = bool(answer.get("existed")) == expected["existed"]
        outcome_ok = norm(answer.get("outcome")) == norm(expected["outcome"])
        replacement = answer.get("replacement")
        expected_replacement = expected["replacement"]
        if expected_replacement is None:
            replacement_ok = replacement in (None, "", "null", "none")
        else:
            replacement_ok = norm(replacement) == norm(expected_replacement)
        return (existed_ok + outcome_ok + replacement_ok) / 3.0
    if cls == "P4":
        def keyset(values):
            return {" ".join(norm(v).replace(".", " ").split()) for v in values}
        got = keyset(answer.get("changed") or [])
        want = keyset(expected["changed"])
        if not got and not want:
            return 1.0
        if not got or not want:
            return 0.0
        tp = len(got & want)
        precision = tp / len(got)
        recall = tp / len(want)
        return 0.0 if tp == 0 else 2 * precision * recall / (precision + recall)
    if cls == "P5":
        return (0.5 * (norm(answer.get("confidence_band")) == norm(expected["confidence_band"])) +
                0.5 * (norm(answer.get("basis")) == norm(expected["basis"])))
    raise ValueError(f"unknown probe class {cls}")


def grade(out_dir, answers_dir):
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    per_class = {m: {} for m in MEDIA}
    sizes = {m: 0 for m in MEDIA}
    missing = []
    for session in manifest["sessions"]:
        sid = session["id"]
        with open(os.path.join(out_dir, "truth", f"{sid}.json"), encoding="utf-8") as handle:
            truth = json.load(handle)
        session_dir = os.path.join(out_dir, "media", sid)
        sizes["journal"] += _dir_bytes(os.path.join(session_dir, "journal"))
        sizes["markdown"] += _dir_bytes(os.path.join(session_dir, "notes.md"))
        sizes["transcript"] += _dir_bytes(os.path.join(session_dir, "transcript.log"))
        for medium in MEDIA:
            answer_path = os.path.join(answers_dir, f"{sid}-{medium}.json")
            if not os.path.isfile(answer_path):
                missing.append(f"{sid}-{medium}")
                continue
            with open(answer_path, encoding="utf-8") as handle:
                answers = json.load(handle)
            for pid, expected in truth.items():
                score = score_answer(expected["class"], expected, answers.get(pid))
                bucket = per_class[medium].setdefault(expected["class"], [])
                bucket.append(score)

    results = {"per_class": {}, "overall": {}, "medium_bytes": sizes,
               "write_ops": {m: sum(s["write_ops"][m] for s in manifest["sessions"])
                             for m in MEDIA},
               "missing_answer_files": missing}
    for medium in MEDIA:
        classes = per_class[medium]
        results["per_class"][medium] = {
            cls: round(sum(scores) / len(scores), 3)
            for cls, scores in sorted(classes.items())}
        all_scores = [s for scores in classes.values() for s in scores]
        results["overall"][medium] = round(sum(all_scores) / len(all_scores), 3) \
            if all_scores else None

    print(json.dumps(results, indent=2))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Belief-recovery benchmark (COG-039)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("generate")
    p.add_argument("--out", required=True)
    p.add_argument("--sessions", type=int, default=4)
    p.add_argument("--seed", type=int, default=20260704)
    p = sub.add_parser("grade")
    p.add_argument("--out", required=True)
    p.add_argument("--answers", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "generate":
        manifest = generate(args.out, args.sessions, args.seed)
        print(json.dumps(manifest, indent=2))
        return 0
    return 0 if grade(args.out, args.answers) else 1


if __name__ == "__main__":
    sys.exit(main())
