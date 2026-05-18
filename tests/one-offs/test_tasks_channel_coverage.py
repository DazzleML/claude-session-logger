"""Tests: v0.3.7-pre #87 — tasks channel coverage extension.

Covers two pieces:
  1. `todo` category (TodoWrite) is now in `_default_category_routes` and
     routes to the tasks channel alongside the Task* family.
  2. New `routing.mcp_server_routes` primitive -- additive channel routing
     keyed by MCP server name (mcp__<server>__<tool>). Default routes
     Todoist (`todoai`) to tasks channel.

Plus the TodoWrite-specific branch in `get_task_content` that summarizes
the todo list for the tasks channel formatter.

Run: python -m pytest tests/one-offs/test_tasks_channel_coverage.py -v
"""

import importlib

# sys.path setup happens in conftest.py
_mod = importlib.import_module("cclogger")

Config = _mod.Config
RoutingConfig = _mod.RoutingConfig
_default_category_routes = _mod._default_category_routes


def _make_logger(config=None):
    """Build a minimal SessionLogger to exercise `_get_channels_for_tool`.

    We don't need a real session directory or event time for routing tests --
    only `self.config.routing` is touched. The logger constructor does a lot
    of disk I/O though, so we use a shim that exposes just the routing method.
    """
    if config is None:
        config = Config()

    # Minimal shim with only the attributes _get_channels_for_tool reads.
    class _Shim:
        pass
    shim = _Shim()
    shim.config = config
    # Bind the method to the shim (acts like an instance method)
    from cclogger.logger import SessionLogger
    return shim, SessionLogger._get_channels_for_tool.__get__(shim, _Shim)


# ============================================================================
# (1) todo category routing -- TodoWrite into tasks channel
# ============================================================================


class TestTodoCategoryRouting:
    def test_default_routes_include_todo(self):
        routes = _default_category_routes()
        assert "todo" in routes
        assert routes["todo"] == ["shell", "sesslog", "tools", "tasks"]

    def test_todo_route_includes_tasks_channel(self):
        routes = _default_category_routes()
        assert "tasks" in routes["todo"]

    def test_todowrite_routes_to_tasks_via_get_channels(self):
        # End-to-end: TodoWrite (category=todo) lands in tasks channel.
        _, get_channels = _make_logger()
        channels = get_channels("TodoWrite", "todo")
        assert "tasks" in channels
        # Other default channels still present
        assert "sesslog" in channels
        assert "tools" in channels
        assert "shell" in channels

    def test_task_category_routing_unchanged(self):
        # Regression: TaskCreate still routes to all four channels.
        _, get_channels = _make_logger()
        channels = get_channels("TaskCreate", "task")
        assert set(channels) == {"shell", "sesslog", "tools", "tasks"}


# ============================================================================
# (2) mcp_server_routes primitive
# ============================================================================


class TestMcpServerRoutesDefault:
    def test_default_includes_todoai(self):
        config = Config()
        assert "todoai" in config.routing.mcp_server_routes
        assert config.routing.mcp_server_routes["todoai"] == ["tasks"]

    def test_default_does_not_include_other_servers(self):
        config = Config()
        # Github, zen, codex etc. are intentionally not in defaults
        assert "github" not in config.routing.mcp_server_routes
        assert "zen" not in config.routing.mcp_server_routes


class TestMcpServerRoutesAdditive:
    def test_todoist_mcp_tool_routes_to_tasks_via_server_route(self):
        # mcp__todoai__create_task should land in tasks (from mcp_server_routes)
        # AND in the category default (mcp falls to _default).
        _, get_channels = _make_logger()
        channels = get_channels("mcp__todoai__todoist_create_task", "mcp")
        assert "tasks" in channels
        # Category default channels also present (mcp falls to _default)
        assert "sesslog" in channels
        assert "shell" in channels
        assert "tools" in channels

    def test_mcp_server_routes_does_not_duplicate_channels(self):
        # If server route includes a channel already in the category route,
        # don't duplicate (additive = union, not concat).
        config = Config()
        config.routing.mcp_server_routes["todoai"] = ["tasks", "sesslog"]
        _, get_channels = _make_logger(config)
        channels = get_channels("mcp__todoai__foo", "mcp")
        # `sesslog` is in default route AND server route -- should appear once
        assert channels.count("sesslog") == 1

    def test_unrelated_mcp_server_not_affected(self):
        # mcp__github__* should NOT route to tasks (github not in default
        # mcp_server_routes).
        _, get_channels = _make_logger()
        channels = get_channels("mcp__github__create_issue", "mcp")
        assert "tasks" not in channels

    def test_non_mcp_tool_unaffected_by_mcp_server_routes(self):
        # A bash tool should not consult mcp_server_routes even if a same-named
        # server exists in the dict.
        config = Config()
        config.routing.mcp_server_routes["bash"] = ["tasks"]
        _, get_channels = _make_logger(config)
        channels = get_channels("Bash", "bash")
        assert "tasks" not in channels

    def test_tool_overrides_replace_skips_mcp_server_routes(self):
        # tool_overrides is the highest-precedence replacement. When it hits,
        # mcp_server_routes is NOT consulted (user is being specific).
        config = Config()
        config.routing.tool_overrides["mcp__todoai__foo"] = ["sesslog"]
        _, get_channels = _make_logger(config)
        channels = get_channels("mcp__todoai__foo", "mcp")
        # User said exactly ["sesslog"], that's what they get.
        assert channels == ["sesslog"]
        assert "tasks" not in channels


class TestMcpServerRoutesUserOverride:
    def test_user_can_add_new_server_mapping(self):
        # Simulating apply_override merge path: user adds `github` mapping.
        from cclogger.config_merge import apply_override_routing_config
        config = Config()
        apply_override_routing_config(
            config.routing,
            {"mcp_server_routes": {"github": ["tasks", "tools"]}},
        )
        assert config.routing.mcp_server_routes["github"] == ["tasks", "tools"]
        # Default todoai mapping is unchanged
        assert config.routing.mcp_server_routes["todoai"] == ["tasks"]

    def test_user_can_clear_default_todoai_route(self):
        # Setting empty list clears server's additive routing
        from cclogger.config_merge import apply_override_routing_config
        config = Config()
        apply_override_routing_config(
            config.routing,
            {"mcp_server_routes": {"todoai": []}},
        )
        assert config.routing.mcp_server_routes["todoai"] == []
        _, get_channels = _make_logger(config)
        channels = get_channels("mcp__todoai__foo", "mcp")
        assert "tasks" not in channels

    def test_user_can_override_to_different_channels(self):
        from cclogger.config_merge import apply_override_routing_config
        config = Config()
        apply_override_routing_config(
            config.routing,
            {"mcp_server_routes": {"todoai": ["convo"]}},
        )
        _, get_channels = _make_logger(config)
        channels = get_channels("mcp__todoai__foo", "mcp")
        assert "convo" in channels
        assert "tasks" not in channels  # original default replaced

    def test_non_dict_input_ignored(self):
        # Defensive: non-dict mcp_server_routes is silently dropped.
        from cclogger.config_merge import apply_override_routing_config
        config = Config()
        apply_override_routing_config(
            config.routing,
            {"mcp_server_routes": "not-a-dict"},
        )
        # Defaults preserved
        assert config.routing.mcp_server_routes["todoai"] == ["tasks"]


# ============================================================================
# (3) TodoWrite formatter -- get_task_content branch
# ============================================================================


class TestTodoWriteTaskContent:
    def test_empty_todos_renders_empty_marker(self):
        from cclogger.formatters.legacy import get_task_content
        raw_json = {"tool_input": {"todos": []}}
        s = get_task_content("TodoWrite", raw_json)
        assert s == "TODOS: (empty)"

    def test_missing_todos_field_renders_empty_marker(self):
        from cclogger.formatters.legacy import get_task_content
        s = get_task_content("TodoWrite", {"tool_input": {}})
        assert s == "TODOS: (empty)"

    def test_status_breakdown_in_output(self):
        from cclogger.formatters.legacy import get_task_content
        raw_json = {"tool_input": {"todos": [
            {"content": "task A", "status": "pending"},
            {"content": "task B", "status": "in_progress"},
            {"content": "task C", "status": "completed"},
            {"content": "task D", "status": "pending"},
        ]}}
        s = get_task_content("TodoWrite", raw_json)
        # 4 items, 2 pending, 1 in_progress, 1 completed
        assert "4 item(s)" in s
        assert "[2p/1ip/1c]" in s
        # First item preview included
        assert "task A" in s

    def test_subject_field_fallback(self):
        # Older Claude Code TodoWrite shape used `subject` rather than `content`
        from cclogger.formatters.legacy import get_task_content
        raw_json = {"tool_input": {"todos": [
            {"subject": "subjectA", "status": "pending"},
        ]}}
        s = get_task_content("TodoWrite", raw_json)
        assert "subjectA" in s

    def test_non_dict_todo_item_handled(self):
        # Resilience: a malformed todos list with non-dict entries shouldn't crash
        from cclogger.formatters.legacy import get_task_content
        raw_json = {"tool_input": {"todos": ["just a string"]}}
        s = get_task_content("TodoWrite", raw_json)
        # Stats: 1 item, 0 of any status, no first_subj
        assert "1 item(s)" in s
        assert "[0p/0ip/0c]" in s

    def test_task_family_still_works_after_todowrite_branch(self):
        # Regression: TodoWrite branch is between TaskGet and the fallback.
        # Make sure TaskCreate/Update/etc still produce expected output.
        from cclogger.formatters.legacy import get_task_content
        raw_json = {"tool_input": {"subject": "Test task", "description": "Desc"}}
        s = get_task_content("TaskCreate", raw_json)
        assert s.startswith("CREATE")
        assert "Test task" in s
