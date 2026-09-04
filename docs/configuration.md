# Configuration Guide

claude-session-logger captures Claude Code session activity into purpose-specific log files. This guide explains the channel/category/route mental model and shows how to customize.

## The Mental Model

Three concepts:

| Concept | What it is | Whose vocabulary | Example |
|---------|-----------|------------------|---------|
| **Tool** | A specific Claude Code tool name, arriving verbatim in the hook payload | **Claude Code's** | `Bash`, `Read`, `Skill` |
| **Category** | A group of related tools | **ours** — this plugin's classification layer | `bash`, `system`, `io`, `task`, `skill`, ... |
| **Channel** | A log file destination | **ours** | `shell`, `sesslog`, `tools`, `convo`, ... |

The mapping chain runs **their names → our categories → our channels**. The category layer exists precisely because the tool vocabulary is Claude Code's and churns with its releases: when a new tool ships, we classify it once and every route keeps working — and until we do, the `unknown` category catches it (surfaced by the `unknowns` channel), so nothing is ever silently dropped.

Each tool belongs to one category. Each category routes to one or more channels. You customize routing to control where each kind of activity lands.

The axis that makes everything else make sense: **a category says what an event *is*; a channel says how its stream is *shown*.** Classification is fixed by the tool's nature; presentation — formatting, verbosity, newline handling, subtype splitting — is each channel's own choice. That's why presentation options (`verbosity`, `subtype_split`, ...) live on channels, never on categories.

## Default Channels

Every channel the plugin ships. The ones marked *opt-in* are defined but disabled — turn one on with `{"routing": {"channels": {"<name>": {"enabled": true}}}}`.

| Channel | File | Ships | Purpose |
|---------|------|-------|---------|
| `shell` | `.shell_*.log` | on | Curated shell-style operations (Bash, PowerShell, Grep, LS, Glob) — copy-pasteable shell history |
| `sesslog` | `.sesslog_*.log` | on | Kitchen-sink "everything" — all activity in one timeline, including every agent's own tool calls, narration and thinking |
| `sesslog-main` | `.sesslog-main_*.log` | on | The session as the main thread saw it: everything in `sesslog` minus each agent's internal legs (its own tool calls, narration, thinking) and minus all thinking. Agent dispatches, START/STOP brackets and reports stay. The one-line off switch is the first example under "Common Customizations" |
| `tools` | `.tools_*.log` | on | AI activity without prose — tools/skills/tasks/shell, but no user/AI text. The "find exact tool calls" investigation view |
| `tasks` | `.tasks_*.log` | on | Task management ops only (TaskCreate, TaskUpdate, etc.) |
| `convo` | `.convo_*.log` | on | User prompts + AI responses + agent dialogue, including thinking |
| `agents` | `.agents_*.log` + `.agents-<type>_*.log` | on | Every subagent's full story, one file per agent type: the dispatch prompt, the agent's own tool calls and narration, its thinking, and its report. Splits per type and collects by `agent_context` (see `collect` below) |
| `unknowns` | `.unknowns_*.log` | on | Tools the plugin doesn't recognize — discovery channel |
| `fileio` | `.fileio_*.log` | opt-in | File operations only (Read, Write, Edit, ...) — the `io` category on its own |
| `tools-output` | `.tools-output_*.log` | opt-in | The rendered output of the tools that carry one (TaskOutput and friends) |
| `thinking` | `.thinking_*.log` | opt-in | Reasoning only: every `{THINK: ...}` and `{AGENT-THINK:<type> ...}` entry, main thread and agents, and nothing else |

See `docs/channels.md` for the auto-generated category/tool reference, including which of Claude Code's outputs land where.

## Configuration Locations

The loader checks two layouts. Use whichever you prefer.

**Single file** (simple, one-glance overview):

```
~/.claude/plugins/settings/session-logger.json
```

**Per-channel directory** (discoverable, one file per channel):

```
~/.claude/plugins/settings/session-logger/
├── _global.json       (top-level: performance, display, action_only, ...)
├── channels/
│   ├── shell.json     ({file_prefix, enabled})
│   ├── tools.json
│   └── ...
└── overrides.json     (category_routes, tool_overrides, mcp_server_routes)
```

If both exist, the directory wins (debug-log warning notes the file is ignored).

## Channel Options

Every channel accepts an `options` object under `routing.channels.<name>.options` — the complete "how is this channel's stream shown" surface (per the mental-model axis above, presentation lives here, never on categories):

| Option | Values | Default | Controls |
|--------|--------|---------|----------|
| `verbosity` | `"full"` / `"preview"` / `"name-only"` / `{"max_chars": N}` / `{"max_lines": N}` / per-role map | global preview length | how much of each entry this channel shows |
| `formatter` | `"default"` / `"chat"` / `"task-only"` | `"default"` | the entry's overall shape (`{ROLE: ...}` hybrid-json, chat-log blocks, task-only lines) |
| `newline_policy` | `"escape"` / `"render"` | `"escape"` | sub-option of the `default` formatter: literal `\n` (grep-friendly single line) vs real newlines. In every channel the entry's frame braces stay matched whatever the body contains (see "Entry framing" in `channels.md`) |
| `role_labels` | `{role: "LABEL"}` | built-ins | display labels (`{USER:`, `{Bash\|Explore:` ...) |
| `suppress_markers` | `true`/`false` | `false` | opt this channel out of SESSION START / COMPACT markers |
| `subtype_split` | `false` / `true` / `["name", ...]` | `false` (`true` on `agents`) | split the stream into `.channel-subtype_*` sibling files (section below) |
| `agent_label` | `"always"` / `"auto"` / `"never"` / `"id"` / `"auto-id"` | `"always"` | how agent identity renders in labels: tool entries (`{Bash\|explore}`) and agent-role lines (`AGENT:explore`); `auto` drops it only where it repeats the channel's own subtype. The id forms add the first 8 characters of the agent's id (`{Bash\|explore/a7c41e0b}`, `AGENT:explore/a7c41e0b`; under `auto-id` inside `.agents-explore_*` just `a7c41e0b`) so concurrent runs of one type read apart, and the `AGENT-START` / `AGENT-STOP` lines carry the full id once (`[id ...]`) -- see "Tell concurrent agents apart" below |
| `collect` | `{attribute: true \| ["value", ...]}` | `{"agent_context": true}` on `agents` only | additionally collect entries by attribute — the emitter/collector model (section below); attributes: `agent_context`, `kind` (`text` / `thinking`), `agent_leg` (`dispatch` / `internal` / `report`), `is_failure` (a failed tool call, marked `[FAILED: reason]` in every channel) |
| `exclude` | `{attribute: true \| ["value", ...]}` | none (`sesslog-main` ships with one) | the mirror of `collect`: drop entries from this channel by the same attributes (section below). Exclusion wins over collection |
| `thinking` | `true` / `false` / unset | unset (on) | whether this channel receives thinking entries (`{THINK: ...}`, `{AGENT-THINK:explore ...}`); `false` is shorthand for `exclude: {"kind": ["thinking"]}` and is inherited by the channel's per-subtype files. Global switch: top-level `"thinking": false` stops extracting thinking anywhere |

### Per-role verbosity (the hierarchy)

`verbosity` accepts a per-role map for direction- and tool-level control, with `_default` as the fallback and hint dicts (`max_chars`/`max_lines`) as values. The shipped `sesslog` default is the canonical example — full content for everything except file-sized payload roles:

```json
{
  "verbosity": {
    "_default": "full",
    "write": {"max_chars": 20},
    "edit": {"max_chars": 20},
    "task-output": {"max_chars": 200}
  }
}
```

Role keys resolve by longest prefix (`agent:user` beats `agent`), and specific tool names work as level-1 keys (`{"PowerShell": {"max_chars": 50}}`).

### `collect`: the emitter/collector model

Every log entry is *emitted* carrying attributes (which agent produced it, its role, ...). A channel's `collect` declares which emitted entries it **additionally** receives, keyed by attribute name — additive, so collected entries keep every channel their category route gave them. This is how `.agents-<type>_*` files carry an agent's *full story*: the `agents` channel ships with `collect: {"agent_context": true}`, so a subagent's internal tool calls and its final report land next to its dispatch prompt instead of scattering.

```json
{
  "routing": {
    "channels": {
      "agents": {"options": {"collect": {"agent_context": ["oracle", "help"]}}}
    }
  }
}
```

Values: `true` = collect any entry with the attribute set; `["value", ...]` = only listed values (case-insensitive). When `subtype_split` is on, collected entries split by the *collected attribute's value* (`.agents-explore_*`), not by the tool's category. Any channel may declare `collect` — define your own collector channel entirely in config. Keys this version recognizes: `agent_context`, `kind`, `agent_leg`, `is_failure`; unknown keys are ignored with a one-time debug-log note, so configs written for newer plugin versions degrade gracefully.

### `exclude`: keeping entries out

`exclude` is `collect` in reverse, with the same keys and the same value forms, and it **wins over both routing and collection** — an entry a route sends here and an entry `collect` pulls in are both dropped when `exclude` matches. Use it to keep one channel quiet without changing where anything else goes:

```json
{
  "routing": {
    "channels": {
      "convo": {"options": {"exclude": {"agent_context": ["untyped"]}}}
    }
  }
}
```

That example hides one particular kind of traffic. Claude Code runs short internal side-queries — activity summaries, prompt suggestions, session memory — that arrive as subagents with **no type**. They are bucketed under the fixed name `untyped` and labelled with the agent's id (`{AGENT:untyped/a000e885 ...}`), so they share one `.agents-untyped_*` file instead of minting a file each. They are included everywhere by default because they are real activity; the line above is how you stop seeing them in the conversation view while keeping them in `sesslog` and the agents feed.

The channel this ships on is `sesslog-main`, whose entire definition is two exclusions (`agent_leg: ["internal"]` plus thinking). Any channel can declare one.

## Common Customizations

### Disable a channel

`sesslog-main` ships enabled; if you find you never read it next to `sesslog`, this is the whole change:
```json
{
  "routing": {
    "channels": {
      "sesslog-main": {"enabled": false}
    }
  }
}
```

Any channel works the same way (single-file layout shown):
```json
{
  "routing": {
    "channels": {
      "unknowns": {"file_prefix": ".unknowns_", "enabled": false}
    }
  }
}
```

### Redirect a category to different channels

```json
{
  "routing": {
    "category_routes": {
      "mcp": ["sesslog"]
    }
  }
}
```

### Force a specific tool to a specific channel set

```json
{
  "routing": {
    "tool_overrides": {
      "Grep": ["shell"]
    }
  }
}
```

### Split a channel by subtype (per-subtype files)

Subtype splitting is a **per-channel** opt-in via `channels.<name>.options.subtype_split` (this field replaced the `routing.subtype_routing` category-wide toggle, which was removed in v0.3.7-pre — that old key is now silently ignored). Splitting the shell channel into `.shell-bash_*.log`, `.shell-powershell_*.log`, ...:

```json
{
  "routing": {
    "channels": {
      "shell": {"options": {"subtype_split": true}}
    }
  }
}
```

Or split the agents channel only for specific subagents (list form):

```json
{
  "routing": {
    "channels": {
      "agents": {"options": {"subtype_split": ["help", "senior-engineer"]}}
    }
  }
}
```

The `agents` channel ships with `subtype_split: true` by default — per-agent files (`.agents-help_*`, `.agents-senior-engineer_*`, ...) appear automatically; every other channel defaults to `false`. Values: `false` (no split) | `true` (split for any subtype) | `["name", ...]` (split only for listed subtypes). See [channels.md](channels.md) for which category each subtype value comes from.

### Disable conversation capture

```json
{
  "routing": {
    "channels": {
      "convo": {"file_prefix": ".convo_", "enabled": false}
    }
  }
}
```

### Turn thinking off (one channel, or everywhere)

Thinking blocks -- Claude's reasoning before it answers, and each agent's reasoning inside its own file -- are recorded by default as `{THINK: ...}` on the main thread and `{AGENT-THINK:explore ...}` inside agents, wherever the narration they belong to goes (`sesslog`, `convo`, `.agents-<type>_*`). To keep a channel free of them:

```json
{
  "routing": {
    "channels": {
      "convo": {"file_prefix": ".convo_", "options": {"thinking": false}}
    }
  }
}
```

`"thinking": false` on `agents` also covers every `.agents-<type>_*` file. To stop extracting thinking at all (no entries built, no cost), set the top-level switch:

```json
{ "thinking": false }
```

The opposite, a reasoning-only stream, is the shipped-but-disabled `thinking` channel: enable it and `.thinking_*` receives every thinking entry (main thread and agents) and nothing else.

### Tell concurrent agents apart (the id label modes)

Two agents of one type dispatched together write interleaved bursts into the same `.agents-<type>_*` file, and by default their lines look alike (`{Bash|explore: ...}`). Set `agent_label` to `id` (or `auto-id`) on the channels where that matters and every label carries the first 8 characters of the agent's id:

```json
{
  "routing": {
    "channels": {
      "convo":  {"options": {"agent_label": "id"}},
      "agents": {"options": {"agent_label": "auto-id"}}
    }
  }
}
```

```
[[2026-09-03 21:52:26]] {Write|general-purpose/a7c41e0b: "...\v0.3.19__u6__sesslog-main.json" ...}
[[2026-09-03 21:52:34]] {AGENT:general-purpose/a7c41e0b: Wrote the mutation file with 12 mutants. ...}
[[2026-09-03 21:52:34]] {AGENT-STOP:general-purpose/a7c41e0b: stopped (0 narration, 0 thinking, report) [id a7c41e0b9d2f53e18] }
```

Inside `.agents-general-purpose_*` under `auto-id` the type is dropped and the id kept (`{Write|a7c41e0b: ...}`, `{AGENT:a7c41e0b ...}`). The `AGENT-START` / `AGENT-STOP` lines carry the full id once, so the short form maps back without leaving the file; a prefix search on the agent's transcript (`agent-a7c41e0b*.jsonl` under `~/.claude/projects/<project>/<session-id>/subagents/`) finds it too. Claude Code's untyped side-queries show `untyped/<8 characters>` in every mode that shows identity.

## Preset Configs (in `examples/`)

Drop-in starting points:

| Preset file | Use case |
|---|---|
| `session-logger.json` | The shipped defaults, written out — every channel named with the state it ships in |
| `session-logger-minimal.json` | Only `.shell_*.log` (copy-pasteable shell history) |
| `session-logger-power-user.json` | Everything enabled including all subtype splits, the reasoning-only channel, and agent ids in labels |
| `session-logger-agent-debug.json` | Focus on agent dialogue with per-agent split, ids in labels, and the side-queries hidden from `convo` |
| `session-logger-conversation-replay.json` | Only conversation prose (user/AI/agent), thinking left out |

Copy any preset to `~/.claude/plugins/settings/session-logger.json` and adjust.

## Customizing Per-Project

The plugin reads global config from `~/.claude/plugins/settings/`. There is currently no per-project override mechanism — see GitHub issue #4 (Session Manager - Project Integration) for related design discussion.

## Schema and IDE Support

The schema at `hooks/schemas/session-logger.schema.json` provides:
- Autocomplete for valid field names in VS Code (and similar)
- Type validation
- Hover tooltips with field descriptions
- Default value hints

To enable in your config file, add `$schema` as the first property:

```json
{
  "$schema": "../hooks/schemas/session-logger.schema.json",
  "routing": { ... }
}
```

## Troubleshooting

- **Channel file not appearing**: Check `enabled: true` for that channel; check the category route includes it; check that no `exclude` on it matches your entries; check `~/.claude/logs/hook-debug.log` for routing decisions.
- **Unknown tool warnings**: First-time encounter of any new tool logs once to `~/.claude/logs/hook-debug.log`. Reset by deleting `~/.claude/logs/.unknown_tool_warnings/`.
- **Both layouts present, only directory loads**: That's intentional — directory wins. Delete one or the other to avoid confusion.
- **Logging feels slow**: every hook invocation times itself and writes a `SLOW` line to `~/.claude/logs/session-logger-perf.log` when it takes more than a second, with the phase breakdown and the file count. An empty file means nothing crossed the threshold. Reading a large agent transcript at the end of a long subagent run is the usual cause of a one-off entry; a steady stream of them is worth reporting.
- **A crowd of `untyped` agents**: expected. Claude Code's internal side-queries stop as typeless subagents; they share one `.agents-untyped_*` file and carry their id in the label. The `exclude` recipe above hides them per channel.
- **`{AGENT:` lines all look alike**: two agents of the same type write to one file. Set `agent_label` to `id` (or `auto-id`) on that channel — see "Tell concurrent agents apart".

## Related

- `docs/channels.md` — auto-generated channel/category/tool reference
- `docs/installation.md` — installation guide
- `examples/` — preset config files
- `hooks/schemas/session-logger.schema.json` — JSON schema
