#!/usr/bin/env python3
"""Generate docs/channels.md from log-command.py's TOOL_CATEGORIES + routing defaults.

Produces a markdown reference table grouping by channel -> category -> tools.
Run from project root:

    python scripts-repo/local/generate_channel_docs.py

Writes to: docs/channels.md
"""

import importlib
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(HOOKS_DIR))
_mod = importlib.import_module("log-command")

TOOL_CATEGORIES = _mod.TOOL_CATEGORIES
_default_channels = _mod._default_channels
_default_category_routes = _mod._default_category_routes
SUBTYPE_EXTRACTORS = _mod.SUBTYPE_EXTRACTORS


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
    by_cat = categorize_tools_by_category()

    lines = []
    lines.append("# Channels Reference")
    lines.append("")
    lines.append("Auto-generated from `hooks/scripts/log-command.py`. "
                 "Do not edit by hand -- regenerate with "
                 "`python scripts-repo/local/generate_channel_docs.py`.")
    lines.append("")

    lines.append("## Channels")
    lines.append("")
    lines.append("| Channel | File prefix | Default | Categories routed here |")
    lines.append("|---------|-------------|---------|------------------------|")
    for name in sorted(channels.keys()):
        ch = channels[name]
        cats_routed = sorted(c for c, chs in routes.items() if name in chs)
        cats_str = ", ".join(f"`{c}`" for c in cats_routed) or "(via _default fallback)"
        enabled = "yes" if ch.enabled else "no"
        lines.append(f"| `{name}` | `{ch.file_prefix}*.log` | {enabled} | {cats_str} |")
    lines.append("")

    lines.append("## Category Routes")
    lines.append("")
    lines.append("| Category | Routes to channels |")
    lines.append("|----------|---------------------|")
    for cat in sorted(routes.keys()):
        chs = ", ".join(f"`{c}`" for c in routes[cat])
        lines.append(f"| `{cat}` | {chs} |")
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

    lines.append("## Subtype Routing (opt-in, v0.3.3+)")
    lines.append("")
    lines.append(
        "Per-category opt-in for splitting log entries into per-subtype channels "
        "(e.g., `.bash-powershell_*.log`, `.mcp-github_*.log`). "
        "Default OFF for all categories. Enable via "
        "`routing.subtype_routing.<category>: true | false | [list]`."
    )
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
