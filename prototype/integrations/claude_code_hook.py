#!/usr/bin/env python3
"""Claude Code -> Cogit bridge (COG-012 passive capture, COG-043 re-anchor).

Three hook events, one script:

- SessionStart: prints a compact belief digest (via `dump`) into the new
  session's context — the agent re-anchors without being asked to.
- PostToolUse: records the tool call as a staged `tool_observation` fact.
- Stop: commits the staged facts as one thought per assistant turn.

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
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit.errors import CogitError  # noqa: E402
from cogit.repo import Repository, init_repository  # noqa: E402


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
        return os.environ["COGIT_PROJECT"]
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


def stage_belief(repo, slug, event, hook_actor_value="claude-code"):
    """Stage one event belief; supersede the previous value of the same
    claim family (same subject/predicate/qualifiers) — current-state
    semantics per claim-modeling Rule 5."""
    qualifiers = {**event["qualifiers"], "project": slug}
    if repo.status()["thought"] is None:
        rows = []  # empty journal: nothing to supersede yet
    else:
        rows = repo.facts(subject=event["subject"], predicate=event["predicate"],
                          project=slug)["facts"]
    family = [row for row in rows if row["qualifiers"] == qualifiers]
    if any(row["object"] == event["object"] for row in family):
        return False  # already the active belief
    for row in family:
        repo.remove_fact(row["assertion"], "superseded")
    repo.add_fact({
        "claim": {
            "type": "claim",
            "kind": "tool_observation",
            "subject": event["subject"],
            "predicate": event["predicate"],
            "object": event["object"],
            "qualifiers": qualifiers,
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "tool", "uri": event["uri"]},
            "confidence_bps": 9900,
            "asserted_at": now_utc(),
            "actor": hook_actor_value,
            "method": {"type": "event_capture"},
        },
    })
    return True


def capture_everything(repo, payload):
    """COG-012 firehose mode (COGIT_CAPTURE=all): every tool call."""
    tool = payload.get("tool_name", "unknown-tool")
    repo.add_fact({
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
    })


def on_post_tool_use(payload):
    repo = journal_repo(payload)
    if os.environ.get("COGIT_CAPTURE", "selective") == "all":
        capture_everything(repo, payload)
        return
    slug = project_slug(payload)
    for event in detect_events(payload):
        stage_belief(repo, slug, event, hook_actor_value=hook_actor(payload))


def on_stop(payload):
    repo = journal_repo(payload)
    status = repo.status()
    if not status["staged"] and not status["removed"]:
        return
    repo.commit_thought(
        f"Turn checkpoint: {len(status['staged'])} captured belief(s)",
        hook_actor(payload),
        now_utc(),
    )


def on_session_start(payload):
    """Print a compact re-anchor digest; SessionStart stdout lands in the
    new session's context (COG-043 — coverage starts with cheap resume)."""
    repo = journal_repo(payload)
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
    print("cogit: call the `dump` MCP tool for the full picture "
          "(facts + introducers + anchors).")


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
