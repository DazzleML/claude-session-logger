"""One-off: verify `verbosity="full"` and `verbosity={"_default": "full"}` are equivalent.

Triggered by user question 2026-05-12: is `_default` redundant with channel-wide
string verbosity? Answer: they converge in step 4 of the 5-level resolver, but
`_default` lets you mix a channel default with role overrides — strings can't.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "hooks" / "scripts"))

from cclogger.formatters.legacy import _resolve_verbosity
from cclogger.models import ChannelOptions


GLOBAL_DEFAULT = 20
ROLES_TO_CHECK = ["user", "ai", "agent", "write", "edit", "bash", "task", "skill"]


def resolve_all(opts: ChannelOptions) -> dict[str, int]:
    return {role: _resolve_verbosity(opts, role, None, GLOBAL_DEFAULT) for role in ROLES_TO_CHECK}


print("=" * 60)
print("Case A: verbosity='full' (string shape)")
print("=" * 60)
a = resolve_all(ChannelOptions(verbosity="full"))
for role, v in a.items():
    print(f"  {role:10} -> {v} ({'full' if v == 0 else 'truncate'})")

print()
print("=" * 60)
print("Case B: verbosity={'_default': 'full'} (per-role dict shape)")
print("=" * 60)
b = resolve_all(ChannelOptions(verbosity={"_default": "full"}))
for role, v in b.items():
    print(f"  {role:10} -> {v} ({'full' if v == 0 else 'truncate'})")

print()
print("=" * 60)
print(f"Equivalent (no role overrides)? {a == b}")
print("=" * 60)

print()
print("=" * 60)
print("Case C: verbosity={'_default': 'full', 'write': {'max_chars': 20}}")
print("=" * 60)
c = resolve_all(ChannelOptions(verbosity={"_default": "full", "write": {"max_chars": 20}}))
for role, v in c.items():
    print(f"  {role:10} -> {v} ({'full' if v == 0 else f'truncate@{v}'})")

print()
print("=" * 60)
print("Can Case C be expressed as a string? NO -- strings can't carry overrides")
print("Can Case A be expressed via _default? YES -- {'_default': 'full'}")
print("=" * 60)
