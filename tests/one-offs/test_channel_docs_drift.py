"""Drift guard: docs/channels.md must match what the generator produces today.

docs/channels.md is generated from the cclogger package's routing defaults by
scripts-repo/local/generate_channel_docs.py. Between 2026-05 (Phase 0b moved
the generator's imports) and 2026-08-13 the generator silently crashed and the
doc rotted for three months while looking authoritative -- five channels and
three routing surfaces missing. This test makes that class of rot loud: change
TOOL_CATEGORIES / default channels / routes / overrides without regenerating,
and this fails in the same test run.

Fix when red:  python scripts-repo/local/generate_channel_docs.py
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "scripts-repo" / "local" / "generate_channel_docs.py"
DOC = REPO / "docs" / "channels.md"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_channel_docs", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_channels_md_matches_generator_output():
    mod = _load_generator()
    expected = mod.generate_markdown()
    actual = DOC.read_text(encoding="utf-8")  # universal newlines: CRLF -> \n
    assert actual == expected, (
        "docs/channels.md is stale relative to the cclogger defaults it "
        "documents. Regenerate it:  python scripts-repo/local/generate_channel_docs.py"
    )
