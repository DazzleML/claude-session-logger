#!/usr/bin/env python3
"""Generate docs/channels.md from the cclogger package's categories + routing defaults.

Produces a markdown reference table grouping by channel -> category -> tools.
Run from project root:

    python scripts-repo/local/generate_channel_docs.py

Writes to: docs/channels.md

History: originally imported TOOL_CATEGORIES etc. as top-level attributes of
log-command.py; those moved into the cclogger package during the Phase 0b
modularization (#37), which silently broke this script (AttributeError) until
the 2026-08-13 #41 docs pass.
"""

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(HOOKS_DIR))

from cclogger.categorize import TOOL_CATEGORIES, SUBTYPE_EXTRACTORS  # noqa: E402
from cclogger.models import (  # noqa: E402
    _default_channels,
    _default_category_routes,
    _default_tool_overrides,
    _default_mcp_server_routes,
)


def categorize_tools_by_category() -> dict[str, list[str]]:
    """Group tools by their category."""
    by_cat: dict[str, list[str]] = {}
    for tool, cat in TOOL_CATEGORIES.items():
        by_cat.setdefault(cat, []).append(tool)
    by_cat.setdefault("mcp", []).append("mcp__<server>__<tool> (dynamic)")
    by_cat.setdefault("unknown", []).append("(any tool not in TOOL_CATEGORIES)")
    return by_cat


def generate_markdown() -> str:
    channels = _default_channels()
    routes = _default_category_routes()
    overrides = _default_tool_overrides()
    mcp_routes = _default_mcp_server_routes()
    by_cat = categorize_tools_by_category()

    lines = []
    lines.append("# Channels Reference")
    lines.append("")
    lines.append("Auto-generated from the `hooks/scripts/cclogger/` package "
                 "(`categorize.py` + `models.py` defaults). "
                 "Do not edit by hand -- regenerate with "
                 "`python scripts-repo/local/generate_channel_docs.py`.")
    lines.append("")

    lines.append("## Channels")
    lines.append("")
    lines.append("| Channel | File prefix | Default | Routed here via |")
    lines.append("|---------|-------------|---------|-----------------|")
    for name in sorted(channels.keys()):
        ch = channels[name]
        parts = []
        cats_routed = sorted(c for c, chs in routes.items() if name in chs)
        if cats_routed:
            parts.append("categories: " + ", ".join(f"`{c}`" for c in cats_routed))
        ov_tools = sorted(t for t, chs in overrides.items() if name in chs)
        if ov_tools:
            parts.append("tool overrides: " + ", ".join(f"`{t}`" for t in ov_tools))
        mcp_srv = sorted(s for s, chs in mcp_routes.items() if name in chs)
        if mcp_srv:
            parts.append("mcp servers (additive): "
                         + ", ".join(f"`{s}`" for s in mcp_srv))
        via = "; ".join(parts) or "(nothing routes here by default)"
        enabled = "yes" if ch.enabled else "no"
        lines.append(f"| `{name}` | `{ch.file_prefix}*.log` | {enabled} | {via} |")
    lines.append("")

    lines.append("## Category Routes")
    lines.append("")
    lines.append(
        "**How routing works, from zero:** every event the logger sees -- a "
        "shell command, a file edit, a user prompt, a subagent report -- is "
        "first classified into a **category** (the *kind* of event it is). "
        "The category then decides which **channels** (the `.xxx_*.log` "
        "files above) receive a copy of the entry: that is the category's "
        "*route*. One event usually lands in several files at once, and "
        "each channel formats it differently for its own purpose. The axis "
        "to hold onto: **a category says what an event *is*; a channel says "
        "how its stream is *shown*** -- which is why presentation options "
        "(verbosity, subtype splitting) live on channels, never on "
        "categories."
    )
    lines.append("")
    lines.append(
        "Reading a route like `bash` -> `shell`, `sesslog`, `tools`: every "
        "shell command is written to `.shell_*.log` (a clean, copy-pasteable "
        "command history), to `.sesslog_*.log` (the kitchen-sink log of the "
        "whole session, full detail), and to `.tools_*.log` (a compact "
        "what-did-the-AI-do view with short previews). Same event, three "
        "views -- channels are *views over the session*, not partitions of "
        "it, so disabling one never loses the event from the others."
    )
    lines.append("")
    lines.append(
        "`_default` is the safety net, not a category: any category without "
        "its own row below uses the `_default` route. And tools the logger "
        "has never heard of get the `unknown` category, whose route includes "
        "the dedicated `unknowns` channel -- so nothing is ever silently "
        "dropped. When several rules apply to one tool, precedence is: a "
        "per-tool override (next section) replaces the category route "
        "entirely; MCP server routes (section after) then add on top."
    )
    lines.append("")
    lines.append("| Category | Routes to channels |")
    lines.append("|----------|---------------------|")
    for cat in sorted(routes.keys()):
        chs = ", ".join(f"`{c}`" for c in routes[cat])
        lines.append(f"| `{cat}` | {chs} |")
    lines.append("")

    lines.append("## Tool Overrides (defaults)")
    lines.append("")
    lines.append(
        "Per-tool routing that REPLACES the tool's category route entirely "
        "(`routing.tool_overrides.<ToolName>`; highest precedence). "
        "Setting an empty list in user config clears the override and falls "
        "back to the category route."
    )
    lines.append("")
    lines.append("| Tool | Routes to channels |")
    lines.append("|------|---------------------|")
    for tool in sorted(overrides.keys()):
        chs = ", ".join(f"`{c}`" for c in overrides[tool])
        lines.append(f"| `{tool}` | {chs} |")
    lines.append("")

    lines.append("## MCP Server Routes (defaults)")
    lines.append("")
    lines.append(
        "Per-server ADDITIVE routing for `mcp__<server>__*` tools "
        "(`routing.mcp_server_routes.<server>`): the server's channels are "
        "unioned into the tool's category route, not replacing it."
    )
    lines.append("")
    lines.append("| MCP server | Adds channels |")
    lines.append("|------------|---------------|")
    for srv in sorted(mcp_routes.keys()):
        chs = ", ".join(f"`{c}`" for c in mcp_routes[srv])
        lines.append(f"| `{srv}` | {chs} |")
    lines.append("")

    lines.append("## Tools by Category")
    lines.append("")
    for cat in sorted(by_cat.keys()):
        chs = routes.get(cat, routes.get("_default", []))
        chs_str = ", ".join(f"`{c}`" for c in chs)
        lines.append(f"### `{cat}` -> {chs_str}")
        lines.append("")
        for tool in sorted(by_cat[cat]):
            lines.append(f"- `{tool}`")
        lines.append("")

    lines.append("## Subtype Splitting (per-channel opt-in, v0.3.7+)")
    lines.append("")
    lines.append(
        "Any channel can split its stream into per-subtype sibling files "
        "(e.g., `.shell-powershell_*.log`, `.mcp-github_*.log`, "
        "`.agents-help_*.log`) via "
        "`routing.channels.<name>.options.subtype_split`:"
    )
    lines.append("")
    lines.append("- `false` (default) -- no splitting for this channel")
    lines.append("- `true` -- split for any subtype the channel's traffic generates")
    lines.append('- `["help", "senior-engineer"]` -- split only for the listed subtype names')
    lines.append("")
    lines.append(
        "The `agents` channel ships with `subtype_split: true`, so per-agent "
        "files appear automatically; every other channel defaults to `false`. "
        "(This per-channel field replaces the `routing.subtype_routing.<category>` "
        "toggle removed in v0.3.7-pre.)"
    )
    lines.append("")
    lines.append("The subtype value itself is extracted per category:")
    lines.append("")
    lines.append("| Category | Subtype Extractor |")
    lines.append("|----------|-------------------|")
    for cat in sorted(SUBTYPE_EXTRACTORS.keys()):
        extractor = SUBTYPE_EXTRACTORS[cat]
        doc = (extractor.__doc__ or "").strip().split("\n")[0]
        lines.append(f"| `{cat}` | {doc} |")
    lines.append("")

    lines.append("## Configuration")
    lines.append("")
    lines.append("Either layout works (loader auto-detects):")
    lines.append("")
    lines.append("**Single file** (simple):")
    lines.append("```")
    lines.append("~/.claude/plugins/settings/session-logger.json")
    lines.append("```")
    lines.append("")
    lines.append("**Per-channel directory** (discoverable):")
    lines.append("```")
    lines.append("~/.claude/plugins/settings/session-logger/")
    lines.append("|-- _global.json")
    lines.append("|-- channels/<name>.json")
    lines.append("`-- overrides.json")
    lines.append("```")
    lines.append("")
    lines.append("If both exist, the directory wins.")
    lines.append("")
    lines.append("Schema: `hooks/schemas/session-logger.schema.json`.")
    lines.append("")

    return "\n".join(lines)


def main():
    output_path = Path(__file__).parent.parent.parent / "docs" / "channels.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = generate_markdown()
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote {output_path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
