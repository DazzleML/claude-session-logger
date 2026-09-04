"""The shipped presets in `examples/` stay true as channels are added.

A preset that promises "only the shell log" keeps that promise only while it
names every channel it does NOT want: an unnamed channel keeps its own
shipped default, so the next channel we add would start writing a file into
a config whose whole point was that it does not. That is not hypothetical --
`sesslog-main` (2026-09-03) was the channel that broke it, and this file is
the guard so the next one cannot.

What is pinned here:
  1. every preset is valid JSON, declares the schema, and survives the real
     config merge with no exception and no unknown-key warning;
  2. `session-logger.json` is the defaults written out -- it names every
     shipped channel with the state that channel actually ships in;
  3. the two "only X" presets end up with exactly the channels they promise;
  4. the option values the presets advertise (`collect`, `exclude`,
     `thinking`, `agent_label`, `subtype_split`) really survive the merge,
     so a preset cannot quietly advertise a key the merge ignores.

Run: python -m pytest tests/one-offs/test_presets_cover_shipped_channels.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"

# The custom-channel demo deliberately defines a channel of its own and says
# nothing about the shipped ones; it is exempt from the coverage pins, not
# from loading cleanly.
CUSTOM_CHANNEL_PRESET = "session-logger-custom-mcp-channel.json"


def _presets() -> list[Path]:
    found = sorted(EXAMPLES.glob("session-logger*.json"))
    assert found, f"no presets found under {EXAMPLES}"
    return found


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _channels(data: dict) -> dict:
    return (data.get("routing") or {}).get("channels") or {}


@pytest.fixture
def quiet_warn_dirs(tmp_path, monkeypatch):
    """Unknown-key warnings write a sentinel file; keep every one of them
    inside tmp_path so a test run never touches the real ~/.claude."""
    import cclogger.debug as dbg
    for name in ("UNKNOWN_TOOL_WARN_DIR", "UNKNOWN_ROLE_WARN_DIR",
                 "UNKNOWN_COLLECT_KEY_WARN_DIR", "UNKNOWN_EXCLUDE_KEY_WARN_DIR"):
        monkeypatch.setattr(dbg, name, tmp_path / name.lower())
    calls: list[str] = []
    monkeypatch.setattr(dbg, "debug_log", lambda msg: calls.append(msg))
    return calls


def _merged(data: dict):
    from cclogger.config_merge import apply_override_config
    from cclogger.models import Config
    cfg = Config()
    apply_override_config(cfg, data)
    return cfg


def _shipped():
    from cclogger.models import _default_channels
    return _default_channels()


# ============================================================================
# Every preset loads
# ============================================================================

class TestEveryPresetLoads:
    @pytest.mark.parametrize("path", _presets(), ids=lambda p: p.name)
    def test_valid_json_with_schema(self, path):
        data = _load(path)
        assert data.get("$schema", "").endswith("session-logger.schema.json"), path.name
        assert isinstance(_channels(data), dict)

    @pytest.mark.parametrize("path", _presets(), ids=lambda p: p.name)
    def test_survives_the_merge_without_warnings(self, path, quiet_warn_dirs):
        cfg = _merged(_load(path))
        assert cfg.routing.channels  # merged into a usable config
        noisy = [m for m in quiet_warn_dirs if "nknown" in m]
        assert noisy == [], (path.name, noisy)

    @pytest.mark.parametrize("path", _presets(), ids=lambda p: p.name)
    def test_names_only_real_channels_and_real_prefixes(self, path):
        if path.name == CUSTOM_CHANNEL_PRESET:
            pytest.skip("defines a custom channel by design")
        shipped = _shipped()
        for name, spec in _channels(_load(path)).items():
            assert name in shipped, f"{path.name}: unknown channel {name}"
            prefix = spec.get("file_prefix")
            if prefix is not None:
                assert prefix == shipped[name].file_prefix, f"{path.name}: {name} prefix drift"


# ============================================================================
# The annotated default IS the defaults
# ============================================================================

class TestAnnotatedDefault:
    def _data(self):
        return _load(EXAMPLES / "session-logger.json")

    def test_names_every_shipped_channel(self):
        named = set(_channels(self._data()))
        missing = sorted(set(_shipped()) - named)
        assert missing == [], f"session-logger.json does not name: {missing}"

    def test_enabled_flags_match_what_ships(self):
        shipped = _shipped()
        for name, spec in _channels(self._data()).items():
            assert spec["enabled"] is shipped[name].enabled, name

    def test_applying_it_changes_no_channel_state(self, quiet_warn_dirs):
        """It is documentation, not configuration: merging it onto the
        defaults leaves every channel's enabled state where it was."""
        from cclogger.models import Config
        before = {n: c.enabled for n, c in Config().routing.channels.items()}
        after = {n: c.enabled for n, c in _merged(self._data()).routing.channels.items()}
        assert after == before


# ============================================================================
# The "only X" presets keep their promise
# ============================================================================

class TestSingleChannelPresets:
    @pytest.mark.parametrize("preset,promised", [
        ("session-logger-minimal.json", {"shell"}),
        ("session-logger-conversation-replay.json", {"convo"}),
    ])
    def test_exactly_the_promised_channels_are_enabled(self, preset, promised, quiet_warn_dirs):
        cfg = _merged(_load(EXAMPLES / preset))
        enabled = {n for n, c in cfg.routing.channels.items() if c.enabled}
        assert enabled == promised, f"{preset}: enabled {sorted(enabled)}"

    @pytest.mark.parametrize("preset", ["session-logger-minimal.json",
                                        "session-logger-conversation-replay.json"])
    def test_they_name_every_shipped_channel(self, preset):
        """The drift guard: naming them all is what makes the promise hold
        when a new channel ships enabled."""
        missing = sorted(set(_shipped()) - set(_channels(_load(EXAMPLES / preset))))
        assert missing == [], f"{preset} does not name: {missing}"

    def test_conversation_replay_leaves_reasoning_out(self, quiet_warn_dirs):
        cfg = _merged(_load(EXAMPLES / "session-logger-conversation-replay.json"))
        opts = cfg.routing.channels["convo"].options
        assert opts.thinking is False
        assert opts.exclude == {"kind": ["thinking"]}  # the sugar folded through the merge


# ============================================================================
# The options a preset advertises really take effect
# ============================================================================

class TestAdvertisedOptionsSurvive:
    def test_power_user_turns_everything_on(self, quiet_warn_dirs):
        cfg = _merged(_load(EXAMPLES / "session-logger-power-user.json"))
        disabled = sorted(n for n, c in cfg.routing.channels.items() if not c.enabled)
        assert disabled == [], disabled
        assert cfg.routing.channels["shell"].options.subtype_split is True
        assert cfg.routing.channels["convo"].options.agent_label == "id"
        assert cfg.routing.channels["agents"].options.agent_label == "auto-id"

    def test_agent_debug_hides_the_side_queries_and_shows_ids(self, quiet_warn_dirs):
        cfg = _merged(_load(EXAMPLES / "session-logger-agent-debug.json"))
        convo = cfg.routing.channels["convo"].options
        agents = cfg.routing.channels["agents"].options
        assert convo.exclude == {"agent_context": ["untyped"]}
        assert convo.agent_label == "id"
        assert agents.collect == {"agent_context": True}
        assert agents.subtype_split is True
        assert agents.agent_label == "auto-id"

    def test_minimal_turns_thinking_off_globally(self, quiet_warn_dirs):
        cfg = _merged(_load(EXAMPLES / "session-logger-minimal.json"))
        assert cfg.thinking is False

    def test_every_agent_label_value_used_is_one_the_merge_accepts(self):
        from cclogger.models import AGENT_LABEL_MODES
        for path in _presets():
            for name, spec in _channels(_load(path)).items():
                mode = (spec.get("options") or {}).get("agent_label")
                if mode is not None:
                    assert mode in AGENT_LABEL_MODES, (path.name, name, mode)
