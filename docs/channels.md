# Channels Reference

Auto-generated from the `hooks/scripts/cclogger/` package (`categorize.py` + `models.py` defaults). Do not edit by hand -- regenerate with `python scripts-repo/local/generate_channel_docs.py`.

## Channels

| Channel | File prefix | Default | Routed here via |
|---------|-------------|---------|-----------------|
| `agents` | `.agents_*.log` | yes | categories: `meta` |
| `convo` | `.convo_*.log` | yes | categories: `message_agent`, `message_ai`, `message_user` |
| `fileio` | `.fileio_*.log` | no | categories: `io` |
| `sesslog` | `.sesslog_*.log` | yes | categories: `_default`, `io`, `message_agent`, `message_ai`, `message_user`, `meta`, `task`, `todo`, `unknown`; tool overrides: `TaskOutput`, `TaskStop` |
| `shell` | `.shell_*.log` | yes | categories: `_default`, `io`, `task`, `todo`; tool overrides: `TaskStop` |
| `tasks` | `.tasks_*.log` | yes | categories: `task`, `todo`; mcp servers (additive): `todoai` |
| `tools` | `.tools_*.log` | yes | categories: `_default`, `io`, `task`, `todo`; tool overrides: `TaskOutput`, `TaskStop` |
| `tools-output` | `.tools-output_*.log` | no | tool overrides: `TaskOutput` |
| `unknowns` | `.unknowns_*.log` | yes | categories: `unknown` |

## Category Routes

**How routing works, from zero:** every event the logger sees -- a shell command, a file edit, a user prompt, a subagent report -- is first classified into a **category** (the *kind* of event it is). The category then decides which **channels** (the `.xxx_*.log` files above) receive a copy of the entry: that is the category's *route*. One event usually lands in several files at once, and each channel formats it differently for its own purpose. The axis to hold onto: **a category says what an event *is*; a channel says how its stream is *shown*** -- which is why presentation options (verbosity, subtype splitting) live on channels, never on categories.

Reading a route like `bash` -> `shell`, `sesslog`, `tools`: every shell command is written to `.shell_*.log` (a clean, copy-pasteable command history), to `.sesslog_*.log` (the kitchen-sink log of the whole session, full detail), and to `.tools_*.log` (a compact what-did-the-AI-do view with short previews). Same event, three views -- channels are *views over the session*, not partitions of it, so disabling one never loses the event from the others.

`_default` is the safety net, not a category: any category without its own row below uses the `_default` route. And tools the logger has never heard of get the `unknown` category, whose route includes the dedicated `unknowns` channel -- so nothing is ever silently dropped. When several rules apply to one tool, precedence is: a per-tool override (next section) replaces the category route entirely; MCP server routes (section after) then add on top.

| Category | Routes to channels |
|----------|---------------------|
| `_default` | `shell`, `sesslog`, `tools` |
| `io` | `shell`, `sesslog`, `tools`, `fileio` |
| `message_agent` | `sesslog`, `convo` |
| `message_ai` | `sesslog`, `convo` |
| `message_user` | `sesslog`, `convo` |
| `meta` | `sesslog`, `agents` |
| `task` | `shell`, `sesslog`, `tools`, `tasks` |
| `todo` | `shell`, `sesslog`, `tools`, `tasks` |
| `unknown` | `sesslog`, `unknowns` |

## Tool Overrides (defaults)

Per-tool routing that REPLACES the tool's category route entirely (`routing.tool_overrides.<ToolName>`; highest precedence). Setting an empty list in user config clears the override and falls back to the category route.

| Tool | Routes to channels |
|------|---------------------|
| `TaskOutput` | `sesslog`, `tools`, `tools-output` |
| `TaskStop` | `shell`, `sesslog`, `tools` |

## MCP Server Routes (defaults)

Per-server ADDITIVE routing for `mcp__<server>__*` tools (`routing.mcp_server_routes.<server>`): the server's channels are unioned into the tool's category route, not replacing it.

| MCP server | Adds channels |
|------------|---------------|
| `todoai` | `tasks` |

## Tools by Category

The tool names below (`Bash`, `Read`, `Agent`, ...) are **Claude Code's own vocabulary** -- they arrive verbatim in the hook payload. The categories grouping them are **ours**: a classification layer this plugin maintains over that vocabulary, so routing survives tool churn upstream. When Claude Code ships a new tool it gets classified once here; until then the `unknown` category catches it (and the `unknowns` channel makes it visible). The mapping chain: their names -> our categories -> our channels.

### `bash` -> `shell`, `sesslog`, `tools`

- `Bash`
- `Glob`
- `Grep`
- `LS`
- `PowerShell`

### `io` -> `shell`, `sesslog`, `tools`, `fileio`

- `Edit`
- `MultiEdit`
- `NotebookEdit`
- `Read`
- `Write`

### `mcp` -> `shell`, `sesslog`, `tools`

- `mcp__<server>__<tool> (dynamic)`

### `meta` -> `sesslog`, `agents`

- `Agent`

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

### `task` -> `shell`, `sesslog`, `tools`, `tasks`

- `TaskCreate`
- `TaskGet`
- `TaskList`
- `TaskOutput`
- `TaskStop`
- `TaskUpdate`

### `todo` -> `shell`, `sesslog`, `tools`, `tasks`

- `TodoWrite`

### `ui` -> `shell`, `sesslog`, `tools`

- `AskUserQuestion`

### `unknown` -> `sesslog`, `unknowns`

- `(any tool not in TOOL_CATEGORIES)`

## Subtype Splitting (per-channel opt-in, v0.3.7+)

Any channel can split its stream into per-subtype sibling files (e.g., `.shell-powershell_*.log`, `.mcp-github_*.log`, `.agents-help_*.log`) via `routing.channels.<name>.options.subtype_split`:

- `false` (default) -- no splitting for this channel
- `true` -- split for any subtype the channel's traffic generates
- `["help", "senior-engineer"]` -- split only for the listed subtype names

The `agents` channel ships with `subtype_split: true`, so per-agent files appear automatically; every other channel defaults to `false`. (This per-channel field replaces the `routing.subtype_routing.<category>` toggle removed in v0.3.7-pre.)

The subtype value itself is extracted per category:

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
