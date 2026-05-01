#!/usr/bin/env python3
"""HV.6 checklist test: customized config still gets new defaults via merge."""
import sys, importlib, pathlib, json, tempfile, os

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "hooks" / "scripts"))
mod = importlib.import_module("log-command")

ConfigLoader = mod.ConfigLoader
ChannelConfig = mod.ChannelConfig

# Simulate a user config WITHOUT unknowns channel or unknown route
user_config = {
    "routing": {
        "channels": {
            "shell": {"file_prefix": ".shell_", "enabled": True},
            "sesslog": {"file_prefix": ".sesslog_", "enabled": True},
            "tasks": {"file_prefix": ".tasks_", "enabled": True},
            "myCustomChannel": {"file_prefix": ".custom_", "enabled": False},
        },
        "category_routes": {
            "_default": ["shell", "sesslog"],
            "task": ["shell", "sesslog", "tasks"],
        }
    }
}

# Write to a temp config file and monkey-patch ConfigLoader.CONFIG_FILE
tmpdir = pathlib.Path(tempfile.mkdtemp())
cfg_file = tmpdir / "session-logger.json"
cfg_file.write_text(json.dumps(user_config))

original_cfg_file = ConfigLoader.CONFIG_FILE
ConfigLoader.CONFIG_FILE = cfg_file

try:
    config = ConfigLoader.load()

    # Test 1: unknowns channel should be present (from defaults, not overridden)
    has_unknowns = "unknowns" in config.routing.channels
    unknowns_enabled = config.routing.channels.get("unknowns", ChannelConfig(file_prefix="")).enabled if has_unknowns else None

    # Test 2: myCustomChannel should also be present (user-added)
    has_custom = "myCustomChannel" in config.routing.channels

    # Test 3: unknown category route should be present (from defaults, not overridden)
    has_unknown_route = "unknown" in config.routing.category_routes
    unknown_route = config.routing.category_routes.get("unknown", [])

    # Test 4: shell should NOT be in the unknown route
    shell_in_unknown = "shell" in unknown_route

    print(f"{'PASS' if has_unknowns else 'FAIL'}: unknowns channel present in merged config (expected: True, got: {has_unknowns})")
    print(f"{'PASS' if unknowns_enabled else 'FAIL'}: unknowns channel enabled (expected: True, got: {unknowns_enabled})")
    print(f"{'PASS' if has_custom else 'FAIL'}: myCustomChannel present in merged config (expected: True, got: {has_custom})")
    print(f"{'PASS' if has_unknown_route else 'FAIL'}: unknown route present in merged config (expected: True, got: {has_unknown_route})")
    print(f"{'PASS' if not shell_in_unknown else 'FAIL'}: shell NOT in unknown route (shell_in_unknown: {shell_in_unknown})")
    print(f"  unknown route = {unknown_route}")

finally:
    ConfigLoader.CONFIG_FILE = original_cfg_file
    import shutil
    shutil.rmtree(tmpdir)
