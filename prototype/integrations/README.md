# Integrations

## Claude Code hook (`claude_code_hook.py`)

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
