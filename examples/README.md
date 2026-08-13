# Configuration Examples

Ready-made presets for `~/.claude/plugins/settings/session-logger.json`. Copy one over that file (or merge the parts you want), restart Claude Code, done. Every file carries a `_comment` explaining itself; all options are documented in [docs/configuration.md](../docs/configuration.md).

| Preset | Use when you want… |
|--------|--------------------|
| [session-logger.json](session-logger.json) | The annotated **default** config — the best starting point for hand-editing; mirrors shipped defaults |
| [session-logger-minimal.json](session-logger-minimal.json) | Just a clean copy-pasteable shell history (`.shell_*` only), nothing else |
| [session-logger-power-user.json](session-logger-power-user.json) | Everything on: all channels + per-subtype splits for shell, MCP, and agents. Maximum visibility |
| [session-logger-agent-debug.json](session-logger-agent-debug.json) | Focused view of subagent behavior — per-agent files (`.agents-help_*`, `.agents-senior-engineer_*`, …) |
| [session-logger-conversation-replay.json](session-logger-conversation-replay.json) | Only the conversation channel, split per direction (user/AI/agent) — transcript-style review |
| [session-logger-custom-mcp-channel.json](session-logger-custom-mcp-channel.json) | A dedicated `.mcp_*.log` for all MCP traffic, optionally split per server (`.mcp-github_*`, …) — also the template for **defining your own channel** |

Presets are merged **per-key** over shipped defaults — a partial file only overrides what it names, so minimal presets stay forward-compatible as new channels ship.
