#!/usr/bin/env python3
"""Claude Code -> Cogit bridge (COG-012 passive capture, COG-043 re-anchor).

Three hook events, one script:

- SessionStart: prints a compact belief digest (via `dump`) into the new
  session's context — the agent re-anchors without being asked to.
- PostToolUse: appends captured events to a per-session BUFFER file —
  never the shared index (COG-062: parallel sessions must not trip each
  other's dirty-index refusals or absorb each other's captures).
- Stop: publishes the buffered events as ONE atomic thought via the
  batch micro-commit; on failure the buffer survives for the next turn.

Wiring (~/.claude/settings.json or project .claude/settings.json):

    {
      "hooks": {
        "SessionStart": [{"hooks": [{"type": "command",
          "command": "python3 /path/to/prototype/integrations/claude_code_hook.py session-start"}]}],
        "PostToolUse": [{"hooks": [{"type": "command",
          "command": "python3 /path/to/prototype/integrations/claude_code_hook.py post-tool-use"}]}],
        "Stop": [{"hooks": [{"type": "command",
          "command": "python3 /path/to/prototype/integrations/claude_code_hook.py stop"}]}]
      }
    }

The journal lives in $COGIT_JOURNAL_DIR (default: ~/.cogit-journal/<project-slug>).
Set COGIT_PROJECT to scope the session-start digest to one project of a
shared journal. Hooks must never break the agent session: every failure
exits 0 silently unless COGIT_HOOK_DEBUG=1.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError  # noqa: E402
from cogit.repo import Repository, init_repository  # noqa: E402
from cogit.secrets import reject_suspected_secrets  # noqa: E402


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def journal_repo(payload):
    cwd = payload.get("cwd") or os.getcwd()
    base = os.environ.get("COGIT_JOURNAL_DIR")
    if base is None:
        slug = re.sub(r"[^a-z0-9]+", "-", cwd.lower()).strip("-") or "default"
        base = os.path.join(os.path.expanduser("~"), ".cogit-journal", slug)
    os.makedirs(base, exist_ok=True)
    init_repository(base)  # idempotent
    return Repository.open(base)


def digest(value, limit=200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text[:limit] if text else "empty"


def project_slug(payload):
    if os.environ.get("COGIT_PROJECT"):
        from cogit.repo import normalize_project_slug
        return normalize_project_slug(os.environ["COGIT_PROJECT"])
    cwd = payload.get("cwd") or os.getcwd()
    return re.sub(r"[^a-z0-9]+", "-", os.path.basename(cwd).lower()).strip("-") or "default"


def hook_actor(payload):
    """Attributable writer identity (COG-052): the hook knows its session."""
    session = str(payload.get("session_id") or "")
    return f"claude-code-{session[:8]}" if session else "claude-code"


# -- selective event capture (COG-044 pilot, mechanism 1) ------------------------

COMMIT_RE = re.compile(r"\[([\w./-]+)\s+([0-9a-f]{7,40})\]\s+(\S.*)")
TEST_CMD_RE = re.compile(r"\b(pytest|unittest|cargo test|interop-test)\b")
TEST_FAIL_RE = re.compile(r"\bFAILED\b|\berror\[|\bfailures=[1-9]|\bpanicked\b|INTEROP FAIL")
TEST_PASS_RE = re.compile(r"\bOK\b|test result: ok|INTEROP OK|\bpassed\b")


def detect_events(payload):
    """Durable-event beliefs only: git commits and test-suite outcomes.
    Deterministic, no LLM in the loop — everything else is noise here."""
    if payload.get("tool_name") != "Bash":
        return []
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    raw = payload.get("tool_response", "")
    response = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
    events = []
    if "git commit" in command:
        # match line-wise: the commit subject must not swallow the stat lines
        match = next((m for line in response.splitlines()
                      if (m := COMMIT_RE.search(line))), None)
        if match:
            branch, commit, subject = match.groups()
            events.append({
                "subject": "git:{}".format(project_slug(payload)),
                "predicate": "head_commit",
                "object": f"{commit[:10]}: {subject[:120]}",
                "qualifiers": {"branch": branch},
                "uri": f"git-commit:{branch}",
            })
    elif TEST_CMD_RE.search(command):
        failed = TEST_FAIL_RE.search(response)
        passed = TEST_PASS_RE.search(response)
        if failed or passed:
            runner = TEST_CMD_RE.search(command).group(1).replace(" ", "-")
            events.append({
                "subject": "test:{}".format(project_slug(payload)),
                "predicate": "suite_status",
                "object": "red" if failed else "green",
                "qualifiers": {"runner": runner},
                "uri": f"test-run:{runner}",
            })
    return events


# -- per-session capture buffer (COG-062): the hook never touches the index ------

def buffer_path(repo, payload):
    session = re.sub(r"[^A-Za-z0-9._-]", "-", str(payload.get("session_id") or ""))
    base = os.path.join(repo.cogit_dir, "hook-buffers")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{session[:32] or 'no-session'}.jsonl")


def buffer_append(repo, payload, entry):
    with open(buffer_path(repo, payload), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def sweep_stale_buffers(repo, max_age_days=7):
    """Dead sessions leave buffers behind; sweep them on session-start."""
    base = os.path.join(repo.cogit_dir, "hook-buffers")
    if not os.path.isdir(base):
        return
    cutoff = time.time() - max_age_days * 86400
    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except OSError:
            continue


def event_doc(event, slug, actor, asserted_at):
    return {
        "claim": {
            "type": "claim",
            "kind": "tool_observation",
            "subject": event["subject"],
            "predicate": event["predicate"],
            "object": event["object"],
            "qualifiers": {**event["qualifiers"], "project": slug},
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "tool", "uri": event["uri"]},
            "confidence_bps": 9900,
            "asserted_at": asserted_at,
            "actor": actor,
            "method": {"type": "event_capture"},
        },
    }


def firehose_doc(payload):
    """COG-012 firehose mode (COGIT_CAPTURE=all): every tool call."""
    tool = payload.get("tool_name", "unknown-tool")
    return {
        "claim": {
            "type": "claim",
            "kind": "tool_observation",
            "subject": f"tool:{tool}",
            "predicate": "returned",
            "object": digest(payload.get("tool_response", "")),
            "qualifiers": {"input": digest(payload.get("tool_input", ""), 120),
                           "project": project_slug(payload)},
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "tool", "uri": f"claude-code:{payload.get('session_id', 'session')}"},
            "confidence_bps": 10000,
            "asserted_at": now_utc(),
            "actor": hook_actor(payload),
            "method": {"type": "tool_result_capture"},
        },
    }


def on_post_tool_use(payload):
    repo = journal_repo(payload)
    if os.environ.get("COGIT_CAPTURE", "selective") == "all":
        buffer_append(repo, payload, {"kind": "doc", "doc": firehose_doc(payload)})
        return
    slug = project_slug(payload)
    for event in detect_events(payload):
        buffer_append(repo, payload, {
            "kind": "event", "event": event, "slug": slug,
            "actor": hook_actor(payload), "at": now_utc(),
        })


def _family_rows(repo, event, slug):
    """Active assertions of the event's exact claim family."""
    if repo.status()["thought"] is None:
        return []
    qualifiers = {**event["qualifiers"], "project": slug}
    rows = repo.facts(subject=event["subject"], predicate=event["predicate"],
                      project=slug)["facts"]
    return [row for row in rows if row["qualifiers"] == qualifiers]


def on_stop(payload):
    repo = journal_repo(payload)
    path = buffer_path(repo, payload)
    if not os.path.isfile(path):
        return
    entries = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    docs, removals, seen_families = [], {}, {}
    for entry in entries:
        if entry.get("kind") == "doc":
            docs.append(entry["doc"])
            continue
        event, slug = entry.get("event") or {}, entry.get("slug", "default")
        family = (event.get("subject"), event.get("predicate"),
                  json.dumps({**event.get("qualifiers", {}), "project": slug},
                             sort_keys=True))
        seen_families[family] = entry  # last observation of a family wins
    for entry in seen_families.values():
        event, slug = entry["event"], entry["slug"]
        rows = _family_rows(repo, event, slug)
        if any(row["object"] == event["object"] for row in rows):
            continue  # already the active belief
        for row in rows:  # current-state semantics (Rule 5)
            removals[row["assertion"]] = {"id": row["assertion"], "reason": "superseded"}
        docs.append(event_doc(event, slug, entry.get("actor", "claude-code"),
                              entry.get("at") or now_utc()))
    clean_docs = []
    for doc in docs:
        try:
            reject_suspected_secrets(doc, "hook-capture")
            clean_docs.append(doc)
        except CogitError:
            continue  # a poisoned capture must not block the whole buffer
    if not clean_docs and not removals:
        os.unlink(path)
        return
    repo.micro_commit_batch(
        clean_docs, list(removals.values()),
        f"Turn checkpoint: {len(clean_docs)} captured belief(s)",
        author=hook_actor(payload),
    )
    # published (or already active): the buffer is consumed. On CogitError
    # (dirty index, contradiction) main() swallows and the buffer SURVIVES
    # for the next turn — captures are never lost to a transient refusal.
    os.unlink(path)


def on_session_start(payload):
    """Print a compact re-anchor digest; SessionStart stdout lands in the
    new session's context (COG-043 — coverage starts with cheap resume)."""
    repo = journal_repo(payload)
    sweep_stale_buffers(repo)
    project = os.environ.get("COGIT_PROJECT")
    doc = repo.dump(project=project, log_limit=8)
    recap = doc["recap"]
    if recap.get("error"):
        print("cogit: journal is empty — no beliefs recorded yet")
        return
    scope = f" (project {project})" if project else ""
    origin = recap.get("from_anchor") or "root"
    print(f"cogit re-anchor{scope}: {len(doc['facts'])} active beliefs; "
          f"since {origin}: {len(recap['thoughts'])} thought(s), "
          f"+{len(recap['added'])}/-{len(recap['removed'])} beliefs. Recent:")
    for thought in doc["log"]:
        print(f"  {thought['timestamp']}  {thought['message']}")
    debt_line = _new_debt_line(repo, project)
    if debt_line:
        print(debt_line)
    print("cogit: call the `dump` MCP tool for the full picture "
          "(facts + introducers + anchors).")


def _new_debt_line(repo, project):
    """COG-067: surface NEW lint debt in the re-anchor digest — the ratchet
    baseline is the newest anchor named lint-baseline-*."""
    try:
        baselines = [a for a in repo.list_anchors()
                     if a["name"].startswith("lint-baseline")]
        if not baselines:
            return None
        newest = max(baselines, key=lambda a: (a["created_at"], a["name"]))
        from lint import lint as run_lint
        report = run_lint(repo, project=project, since=newest["name"])
        new = report["baseline"]["new"]
        if not new:
            return f"cogit lint: no new debt since {newest['name']} — keep it that way."
        return (f"cogit lint: {new} NEW finding(s) since {newest['name']} "
                f"({report['baseline']['new_warnings']} warn) — run lint"
                f"(project={project or 'all'}, since='{newest['name']}') and fix "
                "with supersede_fact/retire_fact before the epic closes.")
    except Exception:  # noqa: BLE001 — the digest must never break a session
        return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "post-tool-use"
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    try:
        if mode == "stop":
            on_stop(payload)
        elif mode == "session-start":
            on_session_start(payload)
        else:
            on_post_tool_use(payload)
    except CogitError as exc:
        # A rejected write (e.g. suspected secret) must not break the session.
        if os.environ.get("COGIT_HOOK_DEBUG"):
            print(f"cogit hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
