"""PoC 3 (2026-09-02): does ANY untyped agent id have material anywhere on disk
beyond the one line our logger recorded?

Maintainer's challenge (verbatim): "It doesn't even make sense why the agent
call would be happening with the new UUID if there truly isn't other material
from that session."

Prediction (pre-written): for every untyped id, there is
  - no <project>/<session>/subagents/agent-<id>.jsonl and no .meta.json
  - no %LOCALAPPDATA%/Temp/claude/<slug>/<session>/tasks/<id>.output
  - no transcript entry whose `agentId` field equals the id
  - no tool_use block referencing the id
and the ONLY main-transcript occurrences are inside tool_result text (our own
`ls`/grep output quoting our log filenames). Control arm: typed subagent ids
(from the subagents/ directory) DO have those artifacts.
REFUTED if any untyped id has a transcript, a meta file, an .output file, or
an agentId-tagged transcript entry.

Usage: python poc_untyped_ids_have_no_other_material.py <session_dir> [...]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ID = re.compile(r"\ba[0-9a-f]{16}\b")
FILE_ID = re.compile(r"^\.agents-(a[0-9a-f]{16})_")


def untyped_ids(session_dir: Path) -> set[str]:
    ids = set()
    for p in session_dir.iterdir():
        if p.is_file() and (m := FILE_ID.match(p.name)):
            ids.add(m.group(1))
    for baks in (session_dir / "baks").glob("*"):
        if baks.is_dir():
            for p in baks.iterdir():
                if m := FILE_ID.match(p.name):
                    ids.add(m.group(1))
    return ids


def where_in_entry(d: dict, ids: set[str]) -> list[str]:
    """Return labels for where any id appears inside one transcript entry."""
    hits = []
    if str(d.get("agentId", "")) in ids:
        hits.append("entry.agentId")
    msg = d.get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        if ID.search(c) and any(t in ids for t in ID.findall(c)):
            hits.append(f"{d.get('type')}.content(str)")
    elif isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            blob = json.dumps(b)
            found = [t for t in ID.findall(blob) if t in ids]
            if found:
                hits.append(f"{d.get('type')}.{b.get('type')}")
    other = {k: v for k, v in d.items() if k not in ("message", "agentId")}
    blob = json.dumps(other)
    if any(t in ids for t in ID.findall(blob)):
        hits.append(f"{d.get('type')}.otherfields")
    return hits


def scan(session_dir: Path) -> bool:
    ids = untyped_ids(session_dir)
    tr = (session_dir / "transcript.jsonl").resolve()
    proj_session = tr.with_suffix("")          # <project>/<session-id>/
    subagents = proj_session / "subagents"
    slug = tr.parent.name
    session_id = tr.stem
    tasks = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "claude" / slug / session_id / "tasks"

    typed_ids = set()
    if subagents.exists():
        for p in subagents.iterdir():
            if m := re.match(r"agent-(a[0-9a-f]{16})\.jsonl$", p.name):
                typed_ids.add(m.group(1))

    def artifacts(idset: set[str]) -> Counter:
        c = Counter()
        for i in idset:
            if (subagents / f"agent-{i}.jsonl").exists():
                c["subagent .jsonl"] += 1
            if (subagents / f"agent-{i}.meta.json").exists():
                c["subagent .meta.json"] += 1
            if tasks.exists() and any(p.name.startswith(i) for p in tasks.iterdir()):
                c["tasks/<id>.output"] += 1
        return c

    # main transcript pass: where do ids appear?
    loc_untyped, loc_typed = Counter(), Counter()
    ids_seen_untyped, ids_seen_typed = set(), set()
    with tr.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if not ID.search(line):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            for lab in where_in_entry(d, ids):
                loc_untyped[lab] += 1
            for lab in where_in_entry(d, typed_ids):
                loc_typed[lab] += 1
            for t in ID.findall(line):
                if t in ids:
                    ids_seen_untyped.add(t)
                elif t in typed_ids:
                    ids_seen_typed.add(t)

    # other files under the project session dir (besides subagents/agent-*.jsonl)
    other_hits = Counter()
    if proj_session.exists():
        for p in proj_session.rglob("*"):
            if p.is_file():
                if any(i in p.name for i in ids):
                    other_hits[f"filename:{p.parent.name}"] += 1
                if p.suffix in (".jsonl", ".json", ".md", ".txt") and p.stat().st_size < 50_000_000:
                    try:
                        blob = p.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if any(t in ids for t in ID.findall(blob)) and p != tr:
                        other_hits[f"content:{p.parent.name}/{p.name[:30]}"] += 1

    au, at = artifacts(ids), artifacts(typed_ids)
    print(f"{session_dir.name[:70]}")
    print(f"  untyped ids: {len(ids)}   typed ids (subagents/): {len(typed_ids)}   tasks dir: {'present' if tasks.exists() else 'absent'}")
    print(f"  UNTYPED artifacts on disk: {dict(au) or 'NONE'}")
    print(f"  TYPED   artifacts on disk: {dict(at) or 'NONE'}   (control)")
    print(f"  UNTYPED ids mentioned anywhere in main transcript: {len(ids_seen_untyped)}  by location: {dict(loc_untyped) or 'NONE'}")
    print(f"  TYPED   ids mentioned anywhere in main transcript: {len(ids_seen_typed)}  by location: {dict(loc_typed) or 'NONE'}   (control)")
    print(f"  UNTYPED ids in other project-session files: {dict(other_hits) or 'NONE'}")
    bad = bool(au) or loc_untyped.get("entry.agentId") or any(k.endswith(".tool_use") for k in loc_untyped)
    print(f"  verdict: {'PREDICTION REFUTED -- untyped ids have other material' if bad else 'PREDICTION HELD -- no material beyond our own log line'}")
    return not bad


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    ok = [scan(Path(a)) for a in argv]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
