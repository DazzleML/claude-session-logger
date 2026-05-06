# Configuration Guide

claude-session-logger captures Claude Code session activity into purpose-specific log files. This guide explains the channel/category/route mental model and shows how to customize.

## The Mental Model

Three concepts:

| Concept | What it is | Example |
|---------|-----------|---------|
| **Tool** | A specific Claude Code tool name | `Bash`, `Read`, `Skill` |
| **Category** | A group of related tools | `bash`, `system`, `io`, `task`, `skill`, ... |
| **Channel** | A log file destination | `shell`, `sesslog`, `tools`, `convo`, ... |

Each tool belongs to one category. Each category routes to one or more channels. You customize routing to control where each kind of activity lands.

## Default Channels

| Channel | File | Purpose |
|---------|------|---------|
| `shell` | `.shell_*.log` | Curated shell-style operations (Bash, PowerShell, Grep, LS, Glob) — copy-pasteable shell history |
| `sesslog` | `.sesslog_*.log` | Kitchen-sink "everything" — all activity in one timeline |
| `tools` | `.tools_*.log` | AI activity without prose — tools/skills/tasks/shell, but no user/AI text. The "find exact tool calls" investigation view |
| `tasks` | `.tasks_*.log` | Task management ops only (TaskCreate, TaskUpdate, etc.) |
| `convo` | `.convo_*.log` | User prompts + AI responses + agent dialogue |
| `unknowns` | `.unknowns_*.log` | Tools the plugin doesn't recognize — discovery channel |

See `docs/channels.md` for the auto-generated category/tool reference.

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
└── overrides.json     (category_routes, tool_overrides, subtype_routing)
```

If both exist, the directory wins (debug-log warning notes the file is ignored).

## Common Customizations

### Disable a channel

Single-file:
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

### Split a category by subtype (per-tool channels)

Splits Bash and PowerShell into separate `.shell-bash_*.log` and `.shell-powershell_*.log`:

```json
{
  "routing": {
    "subtype_routing": {
      "bash": true
    }
  }
}
```

Or split only specific subagents:

```json
{
  "routing": {
    "subtype_routing": {
      "meta": ["help", "senior-engineer"]
    }
  }
}
```

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

## Preset Configs (in `examples/`)

Drop-in starting points:

| Preset file | Use case |
|---|---|
| `session-logger.json` | Default — all channels enabled, no subtype splits |
| `session-logger-minimal.json` | Only `.shell_*.log` (copy-pasteable shell history) |
| `session-logger-power-user.json` | Everything enabled including all subtype splits |
| `session-logger-agent-debug.json` | Focus on agent dialogue with per-agent split |
| `session-logger-conversation-replay.json` | Only conversation prose (user/AI/agent) |

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

- **Channel file not appearing**: Check `enabled: true` for that channel; check the category route includes it; check `~/.claude/logs/hook-debug.log` for routing decisions.
- **Unknown tool warnings**: First-time encounter of any new tool logs once to `~/.claude/logs/hook-debug.log`. Reset by deleting `~/.claude/logs/.unknown_tool_warnings/`.
- **Both layouts present, only directory loads**: That's intentional — directory wins. Delete one or the other to avoid confusion.

## Related

- `docs/channels.md` — auto-generated channel/category/tool reference
- `docs/installation.md` — installation guide
- `examples/` — preset config files
- `hooks/schemas/session-logger.schema.json` — JSON schema
