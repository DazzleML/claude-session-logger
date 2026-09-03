"""PoC (falsification test, 2026-09-02): are the untyped SubagentStops progress
snapshots OF RUNNING TYPED SUBAGENTS, or something else?

Hypothesis H: Claude Code forks a running typed subagent's conversation every
~30s to summarize its activity (AgentSummary-shaped); those forks stop with
`agent_type: ''`, and our logger records each as `{AGENT:a<16hex>: <phrase>}`.

Prediction P (written before running):
  P1  >= 85% of untyped stop timestamps fall inside some typed agent's run
      window [dispatch, report] (windows taken from the same .sesslog).
  P2  the untyped rate OUTSIDE windows (per active hour) is < 10% of the rate
      INSIDE windows.  (control arm: agent-free active time)
  P3  inside windows, the median gap between consecutive untyped stops is in
      [20s, 90s].
H is REFUTED if P1 or P2 fails. P3 failing alone narrows (some other periodic
producer) without refuting.

Method: parse `.sesslog_*` of a session dir. Typed windows = each
`{Agent: ...}` dispatch line paired FIFO with the next `{AGENT:<type>: ...}`
report line (the dispatch line does not name the type, so pairing is by
order; overlapping agents make windows a superset, which only makes P1 EASIER
to pass -- so P2's control arm is the load-bearing half). Untyped stops =
`{AGENT:a<16hex>: ...}` lines. "Active time" = union of [user prompt, next
USER/AI line] gaps under 30 min, so long idle stretches are excluded from
both arms.

Usage: python poc_untyped_stops_track_typed_agents.py <session_dir> [...]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

TS = re.compile(r"^\[\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\] \{(.*)$")
UNTYPED = re.compile(r"^AGENT:a[0-9a-f]{16}:")
TYPED_REPORT = re.compile(r"^AGENT:[A-Za-z][A-Za-z0-9-]*:")
DISPATCH = re.compile(r"^Agent: ")
USER = re.compile(r"^USER:")
AI = re.compile(r"^AI:")


def parse(sesslog: Path):
    events = []
    for line in sesslog.open(encoding="utf-8", errors="replace"):
        m = TS.match(line)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        body = m.group(2)
        if UNTYPED.match(body):
            kind = "untyped"
        elif TYPED_REPORT.match(body):
            kind = "report"
        elif DISPATCH.match(body):
            kind = "dispatch"
        elif USER.match(body):
            kind = "user"
        elif AI.match(body):
            kind = "ai"
        else:
            kind = "tool"
        events.append((t, kind))
    return events


def windows(events):
    """FIFO-pair dispatches with reports -> [(start, end)]."""
    open_starts, out = [], []
    for t, k in events:
        if k == "dispatch":
            open_starts.append(t)
        elif k == "report" and open_starts:
            out.append((open_starts.pop(0), t))
    # unmatched dispatches: assume they ran until the last event
    last = events[-1][0] if events else None
    out += [(s, last) for s in open_starts]
    return merge(out)


def merge(ivs):
    ivs = sorted(ivs)
    out = []
    for s, e in ivs:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def active_intervals(events, idle=timedelta(minutes=30)):
    """Union of gaps between consecutive events shorter than `idle`."""
    ts = [t for t, _ in events]
    ivs = [(a, b) for a, b in zip(ts, ts[1:]) if b - a < idle]
    return merge(ivs)


def inside(t, ivs):
    return any(s <= t <= e for s, e in ivs)


def total_seconds(ivs):
    return sum((e - s).total_seconds() for s, e in ivs)


def intersect(a, b):
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if s < e:
                out.append((s, e))
    return merge(out)


def subtract(a, b):
    """a minus b, both merged interval lists."""
    out = []
    for s, e in a:
        cur = s
        for bs, be in b:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
        if cur < e:
            out.append((cur, e))
    return out


def run(session_dir: Path) -> bool:
    logs = sorted(session_dir.glob(".sesslog_*"))
    if not logs:
        print(f"{session_dir.name[:70]}: no .sesslog file")
        return False
    events = parse(logs[0])
    unt = [t for t, k in events if k == "untyped"]
    win = windows(events)
    act = active_intervals(events)
    win_act = intersect(win, act)
    free_act = subtract(act, win_act)

    n = len(unt)
    n_in = sum(1 for t in unt if inside(t, win))
    n_out = n - n_in
    h_in = total_seconds(win_act) / 3600 or float("nan")
    h_out = total_seconds(free_act) / 3600 or float("nan")
    rate_in = n_in / h_in if h_in == h_in and h_in > 0 else float("nan")
    rate_out = n_out / h_out if h_out == h_out and h_out > 0 else float("nan")

    ins = sorted(t for t in unt if inside(t, win))
    gaps = sorted((b - a).total_seconds() for a, b in zip(ins, ins[1:]) if (b - a).total_seconds() < 600)
    med_gap = gaps[len(gaps) // 2] if gaps else float("nan")

    p1 = n and n_in / n >= 0.85
    p2 = (rate_in == rate_in) and (rate_out != rate_out or rate_out < 0.10 * rate_in)
    p3 = 20 <= med_gap <= 90
    print(f"{session_dir.name[:70]}")
    print(f"  untyped stops: {n}   typed windows: {len(win)}   dispatches: {sum(1 for _,k in events if k=='dispatch')}   reports: {sum(1 for _,k in events if k=='report')}")
    print(f"  P1 inside-window share: {n_in}/{n} = {100*n_in/n if n else 0:.1f}%   -> {'PASS' if p1 else 'FAIL'}")
    print(f"  P2 rate inside {rate_in:.1f}/h over {h_in:.2f}h  vs outside {rate_out:.1f}/h over {h_out:.2f}h (n_out={n_out})   -> {'PASS' if p2 else 'FAIL'}")
    print(f"  P3 median in-window gap: {med_gap:.0f}s (n={len(gaps)})   -> {'PASS' if p3 else 'FAIL'}")
    verdict = "H SUPPORTED" if (p1 and p2) else "H REFUTED"
    print(f"  verdict: {verdict}{'' if p3 else ' (P3 narrowed: cadence off)'}")
    return bool(p1 and p2)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    ok = [run(Path(a)) for a in argv]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
