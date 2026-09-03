"""PoC 2b (2026-09-02): classify each untyped SubagentStop message against the
session TRANSCRIPT (not .convo -- the Stop hook only logs a turn's assistant
text at turn end, so .convo cannot see in-progress text; the transcript can).

Classes, tested in order, per untyped message U (normalized, first 60 chars):
  assistant-echo : U is a prefix of / contained in an ASSISTANT text block
                   whose transcript timestamp is within [-60 min, +2 min] of U
  user-echo      : same test against a real USER prompt (string content, or
                   text blocks not carrying tool_result)
  generated      : neither -- the text exists nowhere else in the record
Predictions (pre-written): the stream is heterogeneous -- no single class
>= 90%; 'generated' is a non-trivial share (>= 20%). Both classes of echo are
by construction redundant with the record; 'generated' is the only class
carrying information not otherwise logged.

Usage: python poc_untyped_taxonomy_vs_transcript.py <session_dir> [...]
(uses <session_dir>/transcript.jsonl and <session_dir>/.convo_*)
"""
from __future__ import annotations

import json
import re
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path

HEAD = re.compile(r"^\[\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\] \{((?:AGENT:)?[^:]+):(.*)$")
PREFIX = 60
LOCAL_UTC_OFFSET = datetime.now().astimezone().utcoffset()  # sesslog stamps are local time


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\n", " ")).strip().lower()


def untyped_entries(convo: Path):
    out, cur = [], None
    for line in convo.open(encoding="utf-8", errors="replace"):
        m = HEAD.match(line)
        if m:
            if cur:
                out.append(cur)
            cur = [datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), m.group(2), m.group(3)]
        elif cur is not None:
            cur[2] += " " + line
    if cur:
        out.append(cur)
    return [(t, norm(x.rstrip("} \n"))) for t, r, x in out if re.fullmatch(r"AGENT:a[0-9a-f]{16}", r)]


def transcript_texts(path: Path):
    """[(local_ts, kind, normalized_text)] for assistant text blocks and real user prompts."""
    rows = []
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        kind = d.get("type")
        if kind not in ("assistant", "user"):
            continue
        ts = d.get("timestamp")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None) + LOCAL_UTC_OFFSET
        except Exception:
            continue
        c = (d.get("message") or {}).get("content")
        texts = []
        if isinstance(c, str):
            texts.append(c)
        elif isinstance(c, list):
            if kind == "user" and any(x.get("type") == "tool_result" for x in c if isinstance(x, dict)):
                continue
            for x in c:
                if isinstance(x, dict) and x.get("type") == "text" and x.get("text"):
                    texts.append(x["text"])
        for x in texts:
            n = norm(x)
            if len(n) >= 20:
                rows.append((t, kind, n))
    rows.sort(key=lambda r: r[0])
    return rows


def classify(u_ts, u_txt, rows, keys, before=timedelta(minutes=60), after=timedelta(minutes=2)):
    key = u_txt[:PREFIX]
    if len(key) < 20:
        return "short"
    lo = bisect_left(keys, u_ts - before)
    hi = bisect_left(keys, u_ts + after)
    hit_kind = None
    for t, kind, txt in rows[lo:hi]:
        if txt.startswith(key) or key in txt[:600]:
            if kind == "assistant":
                return "assistant-echo"
            hit_kind = "user-echo"
    return hit_kind or "generated"


def run(session_dir: Path) -> None:
    convo = sorted(session_dir.glob(".convo_*"))
    tr = session_dir / "transcript.jsonl"
    if not convo or not tr.exists():
        print(f"{session_dir.name[:70]}: missing .convo or transcript.jsonl")
        return
    ents = untyped_entries(convo[0])
    rows = transcript_texts(tr)
    keys = [r[0] for r in rows]
    counts = {}
    examples = {}
    for t, x in ents:
        c = classify(t, x, rows, keys)
        counts[c] = counts.get(c, 0) + 1
        examples.setdefault(c, []).append(f"{t:%m-%d %H:%M:%S} {x[:80]}")
    n = len(ents)
    print(f"{session_dir.name[:70]}")
    print(f"  untyped: {n}   transcript text rows: {len(rows)}")
    for c, k in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {c:15s} {k:5d}  {100*k/n:5.1f}%")
    top = max(counts.values()) / n if n else 0
    gen = counts.get("generated", 0) / n if n else 0
    print(f"  prediction 'no class >= 90%': {'PASS' if top < 0.9 else 'FAIL'}   'generated >= 20%': {'PASS' if gen >= 0.2 else 'FAIL'}")
    for c in ("generated", "user-echo", "assistant-echo"):
        for e in examples.get(c, [])[:3]:
            print(f"    [{c}] {e}")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for a in argv:
        run(Path(a))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
