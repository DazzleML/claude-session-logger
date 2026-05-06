# Channels Reference

Auto-generated from `hooks/scripts/log-command.py`. Do not edit by hand -- regenerate with `python scripts-repo/local/generate_channel_docs.py`.

## Channels

| Channel | File prefix | Default | Categories routed here |
|---------|-------------|---------|------------------------|
| `sesslog` | `.sesslog_*.log` | yes | `_default`, `task`, `unknown` |
| `shell` | `.shell_*.log` | yes | `_default`, `task` |
| `tasks` | `.tasks_*.log` | yes | `task` |
| `tools` | `.tools_*.log` | yes | `_default`, `task` |
| `unknowns` | `.unknowns_*.log` | yes | `unknown` |

## Category Routes

| Category | Routes to channels |
|----------|---------------------|
| `_default` | `shell`, `sesslog`, `tools` |
| `task` | `shell`, `sesslog`, `tools`, `tasks` |
| `unknown` | `sesslog`, `unknowns` |

## Tools by Category

### `bash` -> `shell`, `sesslog`, `tools`

- `Bash`
- `Glob`
- `Grep`
- `LS`
- `PowerShell`

### `io` -> `shell`, `sesslog`, `tools`

- `Edit`
- `MultiEdit`
- `NotebookEdit`
- `Write`

### `mcp` -> `shell`, `sesslog`, `tools`

- `mcp__<server>__<tool> (dynamic)`

### `meta` -> `shell`, `sesslog`, `tools`

- `Task`

### `search` -> `shell`, `sesslog`, `tools`

- `WebFetch`
- `WebSearch`
- `tool_search_tool_bm25`
- `tool_search_tool_regex`

### `skill` -> `shell`, `sesslog`, `tools`

- `Skill`

### `system` -> `shell`, `sesslog`, `tools`

- `EnterPlanMode`
- `ExitPlanMode`
- `Read`

### `task` -> `shell`, `sesslog`, `tools`, `tasks`

- `TaskCreate`
- `TaskGet`
- `TaskList`
- `TaskOutput`
- `TaskStop`
- `TaskUpdate`

### `todo` -> `shell`, `sesslog`, `tools`

- `TodoWrite`

### `ui` -> `shell`, `sesslog`, `tools`

- `AskUserQuestion`

### `unknown` -> `sesslog`, `unknowns`

- `(any tool not in TOOL_CATEGORIES)`

## Subtype Routing (opt-in, v0.3.3+)

Per-category opt-in for splitting log entries into per-subtype channels (e.g., `.bash-powershell_*.log`, `.mcp-github_*.log`). Default OFF for all categories. Enable via `routing.subtype_routing.<category>: true | false | [list]`.

| Category | Subtype Extractor |
|----------|-------------------|
| `bash` | For bash category, the tool name itself is the subtype (Bash, PowerShell, etc.). |
| `mcp` | For MCP tools, extract the server name from mcp__servername__toolname. |
| `meta` | For Task subagent invocations, extract the subagent_type. |
| `skill` | For Skill invocations, extract the skill name from the input. |

## Configuration

Either layout works (loader auto-detects):

**Single file** (simple):
```
~/.claude/plugins/settings/session-logger.json
```

**Per-channel directory** (discoverable):
```
~/.claude/plugins/settings/session-logger/
|-- _global.json
|-- channels/<name>.json
`-- overrides.json
```

If both exist, the directory wins.

Schema: `hooks/schemas/session-logger.schema.json`.
