"""PoC 2 (falsification test, 2026-09-02): do untyped SubagentStop entries carry
UNIQUE information, or are they verbatim copies of text already in the record?

Observation that motivated this: this session's only untyped entry was the
opening of the main thread's own reply, verbatim. Claude Code's forked
side-queries (prompt suggestion, session memory, agent summary, memory
extraction -- all `skipTranscript`) fork the CURRENT conversation; on stop,
`last_assistant_message` is `getLastAssistantMessage(messages)` over the
fork's message list, which includes the parent's history.

Hypothesis H2: most untyped entries duplicate an assistant/agent text already
logged in the same session's .convo channel.

Prediction P (pre-written):
  P1  >= 60% of untyped entries are a verbatim prefix (first 60 chars) of some
      AI: or AGENT:<type>: entry in .convo that is timestamped within
      [-15 min, +15 min] of the untyped entry.
  Control: shuffle the pairing (compare each untyped entry against AI entries
      from a window 6 hours away) -- expected match rate near 0%. If the
      control also matches highly, the test is measuring generic phrasing,
      not duplication, and P1 is void.
H2 REFUTED if P1 < 60% (with a sane control). If P1 passes, untyped entries
are redundant with the record and their "keep" value is navigation only.

Usage: python poc_untyped_content_is_duplicate.py <session_dir> [...]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Role is `AI`, `USER`, `Bash`, ... or `AGENT:<type-or-id>` (two colon-separated parts).
HEAD = re.compile(r"^\[\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\] \{((?:AGENT:)?[^:]+):(.*)$")
PREFIX = 60


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\n", " ")).strip().lower()


def parse_convo(path: Path):
    """Return list of (ts, role, text) with multi-line bodies joined."""
    out = []
    cur = None
    for line in path.open(encoding="utf-8", errors="replace"):
        m = HEAD.match(line)
        if m:
            if cur:
                out.append(cur)
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            cur = [ts, m.group(2), m.group(3)]
        elif cur is not None:
            cur[2] += " " + line
    if cur:
        out.append(cur)
    return [(t, r, norm(x.rstrip("} \n"))) for t, r, x in out]


def run(session_dir: Path, window=timedelta(minutes=15), control_shift=timedelta(hours=6)) -> bool:
    convos = sorted(session_dir.glob(".convo_*"))
    if not convos:
        print(f"{session_dir.name[:70]}: no .convo")
        return False
    entries = parse_convo(convos[0])
    untyped = [(t, x) for t, r, x in entries if re.fullmatch(r"agent:a[0-9a-f]{16}", r.lower())]
    sources = [(t, x) for t, r, x in entries if r == "AI" or (r.startswith("AGENT:") and not re.fullmatch(r"AGENT:a[0-9a-f]{16}", r))]

    def matches(u_ts, u_txt, shift=timedelta(0)):
        key = u_txt[:PREFIX]
        if len(key) < 20:
            return False
        for s_ts, s_txt in sources:
            if abs((s_ts - (u_ts + shift))) <= window and (s_txt.startswith(key) or key in s_txt[:400]):
                return True
        return False

    n = len(untyped)
    hit = sum(1 for t, x in untyped if matches(t, x))
    ctl = sum(1 for t, x in untyped if matches(t, x, control_shift))
    share = 100 * hit / n if n else 0
    cshare = 100 * ctl / n if n else 0
    p1 = n and share >= 60
    sane = cshare < 15
    print(f"{session_dir.name[:70]}")
    print(f"  untyped entries: {n}   AI/typed-agent source entries: {len(sources)}")
    print(f"  P1 verbatim-prefix match within +/-15min: {hit}/{n} = {share:.1f}%   -> {'PASS' if p1 else 'FAIL'}")
    print(f"  control (sources shifted 6h): {ctl}/{n} = {cshare:.1f}%   -> {'sane' if sane else 'NOT SANE (generic phrasing)'}")
    print(f"  verdict: {'H2 SUPPORTED' if (p1 and sane) else 'H2 REFUTED' if sane else 'VOID'}")
    # show a few non-matching examples for eyeballing
    miss = [(t, x) for t, x in untyped if not matches(t, x)][:5]
    for t, x in miss:
        print(f"    unmatched: {t:%H:%M:%S} {x[:90]}")
    return bool(p1 and sane)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    ok = [run(Path(a)) for a in argv]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
