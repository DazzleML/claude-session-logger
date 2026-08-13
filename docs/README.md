# Documentation

| Doc | What it covers |
|-----|----------------|
| [installation.md](installation.md) | All install methods (marketplace, local clone, `--plugin-dir`, manual), **updating** (incl. multi-user machines), migrating from a manual install, troubleshooting, uninstalling |
| [configuration.md](configuration.md) | The settings file (`~/.claude/plugins/settings/session-logger.json`), every option with defaults, JSON Schema / IDE autocompletion, per-channel config |
| [channels.md](channels.md) | **Auto-generated reference**: every shipped channel, its file prefix, defaults, and which tool categories route to it |
| [log-channels.md](log-channels.md) | Conceptual guide to the log file types — what each `.sesslog_*` / `.shell_*` / `.tools_*` / `.convo_*` … file contains and when to read which |
| [dev.md](dev.md) | Contributor guide: project layout, local plugin testing, version management (`sync-versions.py`), test suite, release workflow |

**Start here:** installing → [installation.md](installation.md); customizing what gets logged → [configuration.md](configuration.md) plus the ready-made presets in [`../examples/`](../examples/README.md); understanding the output files → [log-channels.md](log-channels.md).
