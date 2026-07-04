# Integrations

## MCP server (`mcp_server.py`) — active use

Exposes Cogit to any MCP client (Claude Code, Claude Desktop) as tools:
`add_fact`, `commit_thought`, `facts`, `recap`, `blame_fact`, `merge`,
`resolve`, `anchor`, `annotate`, `bisect_thought`, `verify`, and more.
Zero dependencies, stdio JSON-RPC, one server per journal. Destructive
maintenance (prune, reflog-expire, rerere --forget) is not exposed
(ADR-0009).

Register with Claude Code:

```sh
claude mcp add cogit -e COGIT_REPO=$HOME/.cogit-journal/my-project \
    -- python3 /ABS/PATH/prototype/integrations/mcp_server.py
```

The journal is initialized on first use. Suggested agent workflow: start a
session with `recap` from your last anchor; record decisions with
`add_fact(commit=true)`; `anchor` milestones; when something turns out
wrong, `blame_fact` it and `bisect_thought` the history. What deserves to
be a fact — and what does not — is `docs/claim-modeling.md`.

## Web viewer (`web_viewer.py`) — read-only UI (COG-038)

A zero-dependency local web page over one journal: thought DAG across all
branches, active beliefs with subject/predicate/project filters, per-fact
introducer (blame), anchors, annotations, and the no-arg recap. Strictly
read-only — a browser has no honest `actor`, so write operations are out
of scope by design, not merely missing (same reasoning as ADR-0009).

```sh
python3 web_viewer.py --repo ~/.cogit-journal/cogit          # http://127.0.0.1:8323/
python3 web_viewer.py --repo ... --snapshot journal.html     # self-contained snapshot
```

The live page polls `/api/state` every 3 s; `--snapshot` embeds the same
JSON into one shareable HTML file. Binds `127.0.0.1` by default and has
no auth — a non-local `--host` is a deliberate operator decision.

## Claude Code hook (`claude_code_hook.py`) — selective capture + re-anchor

Default capture is **selective** (COG-044 pilot): only durable events
become staged beliefs — git commits (`git:<project> head_commit`, the
previous value is superseded) and test-suite outcomes
(`test:<project> suite_status = green|red`). One thought per assistant
turn commits whatever was staged. Set `COGIT_CAPTURE=all` for the old
firehose mode (every tool call — noisy, COG-012). For batch manual
journaling from the main loop the MCP server offers `record` (N facts +
optional removals -> one thought).

A third mode, `session-start` (COG-043), prints a compact belief digest
(via `dump`) into every new session's context — the agent re-anchors
automatically instead of being told to run `recap`. Set `COGIT_PROJECT`
to scope the digest in a shared journal.

Enable in `~/.claude/settings.json` (or a project's `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command",
        "command": "python3 /ABS/PATH/prototype/integrations/claude_code_hook.py session-start"}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command",
        "command": "python3 /ABS/PATH/prototype/integrations/claude_code_hook.py post-tool-use"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command",
        "command": "python3 /ABS/PATH/prototype/integrations/claude_code_hook.py stop"}]}
    ]
  }
}
```

- Journal location: `$COGIT_JOURNAL_DIR` or `~/.cogit-journal/<project-slug>/`.
- Failures never break the session (exit 0); set `COGIT_HOOK_DEBUG=1` to see
  errors. Suspected secrets are rejected by the store, so such tool results
  are simply not journaled.

Inspect the journal:

```sh
cd ~/.cogit-journal/<slug>
python3 -m cogit log | head          # thoughts per turn
python3 -m cogit log -g              # pointer movement
python3 -m cogit verify
```
