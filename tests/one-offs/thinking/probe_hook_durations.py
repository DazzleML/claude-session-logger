"""Probe: measure per-invocation hook durations from ~/.claude/logs/hook-debug.log.

Context (2026-09-02): a config-tool session reported
"UserPromptSubmit hook timed out after 30s -- output discarded" and its
sesslog dir holds ~1,100 one-line `.agents-<agent_id>_*` files. This probe
answers: how long do our hook invocations actually take, by event and by
session, and did any approach the 30s wall?

Method: the debug log is one line per step, timestamped. Each invocation
begins with "Hook started (Python)". Blocks from concurrent sessions can
interleave, so a block's duration is measured as the span from its
"Hook started" line to the LAST line that belongs to it -- attributed via
the session id in "Wrote session state to ...<uuid>.json" / "Logged to".
Lines with no session attribution are assigned to the most recent block.
Interleaving makes this an approximation; large outliers are robust to it.

Usage: python probe_hook_durations.py [--session <uuid-prefix>] [--top N]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".claude" / "logs" / "hook-debug.log"
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+): (.*)$")
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def parse(path: Path):
    blocks = []  # dicts: start, end, event, session, lines
    cur = None
    by_session_open = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = TS_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
            msg = m.group(2)
            if msg.startswith("Hook started"):
                cur = {"start": ts, "end": ts, "event": None, "session": None, "n": 1}
                blocks.append(cur)
                continue
            if cur is None:
                continue
            sid = None
            um = UUID_RE.search(msg)
            if um:
                sid = um.group(1)
            target = cur
            if sid is not None:
                if cur["session"] is None:
                    cur["session"] = sid
                    by_session_open[sid] = cur
                elif cur["session"] != sid and sid in by_session_open:
                    target = by_session_open[sid]
                elif cur["session"] != sid:
                    target = cur
            if msg.startswith("Hook event:"):
                target["event"] = msg.split(":", 1)[1].strip()
            target["end"] = max(target["end"], ts)
            target["n"] += 1
    return blocks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="uuid prefix filter")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--log", default=str(LOG))
    a = ap.parse_args(argv)

    blocks = parse(Path(a.log))
    if a.session:
        blocks = [b for b in blocks if (b["session"] or "").startswith(a.session)]
    for b in blocks:
        b["dur"] = (b["end"] - b["start"]).total_seconds()

    print(f"blocks: {len(blocks)}")
    by_event = defaultdict(list)
    for b in blocks:
        by_event[b["event"] or "?"].append(b["dur"])
    print("\nevent            count     p50      p90      p99      max")
    for ev, ds in sorted(by_event.items(), key=lambda kv: -len(kv[1])):
        ds.sort()
        n = len(ds)
        q = lambda p: ds[min(n - 1, int(p * n))]
        print(f"{ev:16s} {n:6d}  {q(.5):7.2f}  {q(.9):7.2f}  {q(.99):7.2f}  {ds[-1]:7.2f}")

    print(f"\ntop {a.top} slowest blocks:")
    for b in sorted(blocks, key=lambda b: -b["dur"])[: a.top]:
        print(f"  {b['dur']:7.2f}s  {b['start']}  {b['event'] or '?':16s} {(b['session'] or '?')[:8]}  lines={b['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
