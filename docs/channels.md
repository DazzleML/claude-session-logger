# Channels Reference

Auto-generated from the `hooks/scripts/cclogger/` package (`categorize.py` + `models.py` defaults). Do not edit by hand -- regenerate with `python scripts-repo/generate_channel_docs.py`.

## Channels

| Channel | File prefix | Default | Routed here via |
|---------|-------------|---------|-----------------|
| `agents` | `.agents_*.log` | yes | categories: `meta` |
| `convo` | `.convo_*.log` | yes | categories: `message_agent`, `message_ai`, `message_user` |
| `fileio` | `.fileio_*.log` | no | categories: `io` |
| `sesslog` | `.sesslog_*.log` | yes | categories: `_default`, `io`, `message_agent`, `message_ai`, `message_user`, `meta`, `task`, `todo`, `unknown`; tool overrides: `TaskOutput`, `TaskStop` |
| `sesslog-main` | `.sesslog-main_*.log` | yes | categories: `_default`, `io`, `message_agent`, `message_ai`, `message_user`, `meta`, `task`, `todo`, `unknown`; tool overrides: `TaskOutput`, `TaskStop` |
| `shell` | `.shell_*.log` | yes | categories: `_default`, `io`, `task`, `todo`; tool overrides: `TaskStop` |
| `tasks` | `.tasks_*.log` | yes | categories: `task`, `todo`; mcp servers (additive): `todoai` |
| `thinking` | `.thinking_*.log` | no | (nothing routes here by default) |
| `tools` | `.tools_*.log` | yes | categories: `_default`, `io`, `task`, `todo`; tool overrides: `TaskOutput`, `TaskStop` |
| `tools-output` | `.tools-output_*.log` | no | tool overrides: `TaskOutput` |
| `unknowns` | `.unknowns_*.log` | yes | categories: `unknown` |

## Category Routes

**How routing works, from zero:** every event the logger sees -- a shell command, a file edit, a user prompt, a subagent report -- is first classified into a **category** (the *kind* of event it is). The category then decides which **channels** (the `.xxx_*.log` files above) receive a copy of the entry: that is the category's *route*. One event usually lands in several files at once, and each channel formats it differently for its own purpose. The axis to hold onto: **a category says what an event *is*; a channel says how its stream is *shown*** -- which is why presentation options (verbosity, subtype splitting) live on channels, never on categories.

Reading a route like `bash` -> `shell`, `sesslog`, `tools`: every shell command is written to `.shell_*.log` (a clean, copy-pasteable command history), to `.sesslog_*.log` (the kitchen-sink log of the whole session, full detail), and to `.tools_*.log` (a compact what-did-the-AI-do view with short previews). Same event, three views -- channels are *views over the session*, not partitions of it, so disabling one never loses the event from the others.

`_default` is the safety net, not a category: any category without its own row below uses the `_default` route. And tools the logger has never heard of get the `unknown` category, whose route includes the dedicated `unknowns` channel -- so nothing is ever silently dropped. When several rules apply to one tool, precedence is: a per-tool override (next section) replaces the category route entirely; MCP server routes (section after) then add on top.

| Category | Routes to channels |
|----------|---------------------|
| `_default` | `shell`, `sesslog`, `sesslog-main`, `tools` |
| `io` | `shell`, `sesslog`, `sesslog-main`, `tools`, `fileio` |
| `message_agent` | `sesslog`, `sesslog-main`, `convo` |
| `message_ai` | `sesslog`, `sesslog-main`, `convo` |
| `message_user` | `sesslog`, `sesslog-main`, `convo` |
| `meta` | `sesslog`, `sesslog-main`, `agents` |
| `task` | `shell`, `sesslog`, `sesslog-main`, `tools`, `tasks` |
| `todo` | `shell`, `sesslog`, `sesslog-main`, `tools`, `tasks` |
| `unknown` | `sesslog`, `sesslog-main`, `unknowns` |

## Tool Overrides (defaults)

Per-tool routing that REPLACES the tool's category route entirely (`routing.tool_overrides.<ToolName>`; highest precedence). Setting an empty list in user config clears the override and falls back to the category route.

| Tool | Routes to channels |
|------|---------------------|
| `TaskOutput` | `sesslog`, `sesslog-main`, `tools`, `tools-output` |
| `TaskStop` | `shell`, `sesslog`, `sesslog-main`, `tools` |

## MCP Server Routes (defaults)

Per-server ADDITIVE routing for `mcp__<server>__*` tools (`routing.mcp_server_routes.<server>`): the server's channels are unioned into the tool's category route, not replacing it.

| MCP server | Adds channels |
|------------|---------------|
| `todoai` | `tasks` |

## Tools by Category

The tool names below (`Bash`, `Read`, `Agent`, ...) are **Claude Code's own vocabulary** -- they arrive verbatim in the hook payload. The categories grouping them are **ours**: a classification layer this plugin maintains over that vocabulary, so routing survives tool churn upstream. When Claude Code ships a new tool it gets classified once here; until then the `unknown` category catches it (and the `unknowns` channel makes it visible). The mapping chain: their names -> our categories -> our channels.

### `bash` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `Bash`
- `Glob`
- `Grep`
- `LS`
- `PowerShell`

### `io` -> `shell`, `sesslog`, `sesslog-main`, `tools`, `fileio`

- `Edit`
- `MultiEdit`
- `NotebookEdit`
- `Read`
- `Write`

### `mcp` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `mcp__<server>__<tool> (dynamic)`

### `meta` -> `sesslog`, `sesslog-main`, `agents`

- `Agent`

### `search` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `WebFetch`
- `WebSearch`
- `tool_search_tool_bm25`
- `tool_search_tool_regex`

### `skill` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `Skill`

### `system` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `EnterPlanMode`
- `ExitPlanMode`

### `task` -> `shell`, `sesslog`, `sesslog-main`, `tools`, `tasks`

- `TaskCreate`
- `TaskGet`
- `TaskList`
- `TaskOutput`
- `TaskStop`
- `TaskUpdate`

### `todo` -> `shell`, `sesslog`, `sesslog-main`, `tools`, `tasks`

- `TodoWrite`

### `ui` -> `shell`, `sesslog`, `sesslog-main`, `tools`

- `AskUserQuestion`

### `unknown` -> `sesslog`, `sesslog-main`, `unknowns`

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

## What Claude Code produces, and where we put it

The tables above map Claude Code's **tool names** to our categories and channels. That is only part of what a session produces: it also emits hook events we may or may not subscribe to, transcript content blocks of more than one kind, and a separate transcript per subagent. This table names the whole surface, so an unrecorded source is a visible empty cell rather than a surprise.

| Claude Code produces | Where it lives | We receive it via | We record it as |
|---|---|---|---|
| Tool call, main thread | `PostToolUse` payload | subscribed | `{Tool: ...}`, by category |
| Tool call inside a subagent | `PostToolUse` payload with `agent_id` | subscribed | the same entry, attributed (`{Bash\|explore: ...}`) and collected into that agent's file |
| Failed tool call | `PostToolUseFailure` payload | subscribed | the same entry plus `[FAILED: reason]` inside the frame |
| Main-thread narration | main transcript, `text` blocks | `Stop` + a byte cursor | `{AI: ...}` |
| Main-thread reasoning | main transcript, `thinking` blocks | `Stop` + the same cursor | `{THINK: ...}` (switchable per channel; off in `sesslog-main`) |
| Agent dispatch | `PostToolUse` for the Agent tool | subscribed | `{Agent: prompt}` |
| Agent kickoff | `SubagentStart` payload | subscribed | `{AGENT-START:<type>: description }` |
| Agent narration | that agent's sidechain transcript | `SubagentStop` + a per-agent cursor | `{AGENT:<type>: ...}` |
| Agent reasoning | that agent's sidechain transcript | the same read | `{AGENT-THINK:<type>: ...}` |
| Agent report | `last_assistant_message`, cross-checked against the transcript's last text block | subscribed | `{AGENT:<type>: ...}`, the final one |
| Agent end | `SubagentStop` | subscribed | `{AGENT-STOP:<type>: stopped (N narration, M thinking, report) }` |
| Typeless side-query | `SubagentStop` with an empty type | subscribed | one line in `.agents-untyped_*`, labelled with the agent's id (nothing else for these exists on disk) |
| User prompt | `UserPromptSubmit` payload | subscribed | `{USER: ...}` |
| Tool output text | `tool_response` | subscribed | rendered for the tools that carry a useful one; a general treatment is open work |
| Attachments, images, system entries | transcripts | not read | nothing -- deliberately out of scope |

Two attributes travel with every entry and are what the channel predicates key on: its **kind** (`text` or `thinking`) and, for agent traffic, its **leg** (`dispatch`, `internal`, or `report`). `sesslog-main` is defined entirely in those terms -- everything except the internal leg and thinking.

## Entry framing: the braces always match

Every entry is framed as `{LABEL: body }` (one line) or, in a `render` channel, `{LABEL:` / body / `}`. The way to walk a log is the editor's brace jump (vim `%`, VS Code bracket matching) from an entry's first `{` to its last `}` -- and editors count every brace in a plain-text file, including the ones inside a body. The body is recorded **verbatim**, so the balance is restored outside the frame:

- for every `{` in the body with no partner, one extra `}` is appended after the frame's closing brace: a body with two unclosed braces ends `}}}`;
- for every `}` in the body with no partner, one extra `{` is inserted after the frame's opening brace: `{{USER:`.

The frame's own braces are always the outermost pair, so the jump from the first `{` lands on the last `}` in every channel, and the number of extra braces says how many strays the body holds -- without guessing where they belong. Balanced bodies (code, JSON, `re:{ ... }` blocks) get no extra braces at all. (Before v0.3.18 a body containing an unbalanced `{` left the entry's frame unmatched for the jump.)

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
