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


def on_post_tool_use(payload):
    repo = journal_repo(payload)
    tool = payload.get("tool_name", "unknown-tool")
    doc = {
        "claim": {
            "type": "claim",
            "kind": "tool_observation",
            "subject": f"tool:{tool}",
            "predicate": "returned",
            "object": digest(payload.get("tool_response", "")),
            "qualifiers": {"input": digest(payload.get("tool_input", ""), 120)},
        },
        "assertion": {
            "type": "assertion",
            "status": "asserted",
            "source": {"type": "tool", "uri": f"claude-code:{payload.get('session_id', 'session')}"},
            "confidence_bps": 10000,
            "asserted_at": now_utc(),
            "actor": "claude-code",
            "method": {"type": "tool_result_capture"},
        },
    }
    repo.add_fact(doc)


def on_stop(payload):
    repo = journal_repo(payload)
    status = repo.status()
    if not status["staged"] and not status["removed"]:
        return
    repo.commit_thought(
        f"Turn checkpoint: {len(status['staged'])} tool observation(s)",
        "claude-code",
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
