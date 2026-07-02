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

## Claude Code hook (`claude_code_hook.py`) — passive journaling

Records every tool call of a Claude Code session as a staged
`tool_observation` fact and commits one thought per assistant turn — an
automatic reasoning journal with full provenance (`blame-fact` a wrong
observation back to the exact turn and tool call).

Enable in `~/.claude/settings.json` (or a project's `.claude/settings.json`):

```json
{
  "hooks": {
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
