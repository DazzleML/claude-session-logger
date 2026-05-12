"""Verify precedence when a verbosity dict contains BOTH a hint key (max_chars)
AND _default. The classification logic decides which wins.

The user's question (2026-05-12): "if both the channel is set and the default
is set and they are set DIFFERENTLY the global channel wins?"

My previous answer claimed max_chars wins. Let me actually verify.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "hooks" / "scripts"))

from cclogger.formatters.legacy import _is_hint_dict, _resolve_verbosity
from cclogger.models import ChannelOptions


GLOBAL_DEFAULT = 20


def show(label: str, verbosity: object) -> None:
    print(f"\n{'-' * 70}")
    print(f"Case: {label}")
    print(f"  verbosity = {verbosity!r}")
    if isinstance(verbosity, dict):
        print(f"  _is_hint_dict?           {_is_hint_dict(verbosity)}")
    result = _resolve_verbosity(ChannelOptions(verbosity=verbosity), "user", None, GLOBAL_DEFAULT)
    print(f"  resolved for 'user'      {result}")
    result = _resolve_verbosity(ChannelOptions(verbosity=verbosity), "write", None, GLOBAL_DEFAULT)
    print(f"  resolved for 'write'     {result}")


show("Pure hint dict (channel-wide truncation)", {"max_chars": 100})
show("Pure _default (channel-wide full)", {"_default": "full"})
show("Mixed: max_chars + _default DIFFERENT values",
     {"max_chars": 100, "_default": "preview"})
show("Mixed: max_chars + _default + role override",
     {"max_chars": 100, "_default": "preview", "write": {"max_chars": 5}})

print()
print("=" * 70)
print("ANSWER: when both max_chars AND _default appear, _is_hint_dict returns")
print("False (because _default is not a hint key), so the dict is treated as")
print("a per-role map. The resolver then walks role-keys, finds none matching,")
print("and lands on _default. max_chars at the top level is SILENTLY IGNORED.")
print("=" * 70)
