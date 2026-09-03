"""PoC: the `.convo_*` frame is ambiguous when a body contains braces or
entry-like lines at column 0 (maintainer report, 2026-09-03 15:00:03).

HISTORY NOTE (same day, later): P3 below tests the *indentation* idea,
which was rejected -- the maintainer's navigation is the editor brace
jump, which indentation does not serve, and indents fight a narrow
terminal. The shipped rule is frame padding (`cclogger.frame.pad_frame`,
design Addendum 4): the body stays verbatim and unmatched braces are
balanced outside the frame (`{{USER:` / `}}}`). P1, P2, P4, P5 and P6 are
the evidence that still stands; the regression test is
tests/one-offs/test_render_frame.py.

Pre-registered predictions (written before running):

  P1  Rendering the maintainer's message through the REAL convo path
      (format_for_channel, chat formatter, RENDER) yields an entry whose
      opening `{USER:` is never closed by a brace-matching read.
      Control: the same message with its one unbalanced `{` removed is
      matched.
  P2  A column-0 rule parser ("an entry starts at `[[ts]] {LABEL:` at
      column 0 and ends at the next `}` alone at column 0") mis-bounds a
      body that contains `}` at column 0, and mis-starts on a body line
      that begins with `[[ts]] {LABEL:`.
  P3  The proposed fix -- indent every body line by two spaces, keep the
      frame at column 0 -- makes the column-0 rule bound every entry of the
      same fixture exactly (starts == ends, one body per start, bodies
      round-trip after de-indent).
  P4  Real population: this session's `.convo_*` file has more column-0
      `}` lines than entry starts (the excess are body braces), i.e. the
      ambiguity is present in the live record, not only in a fixture.
  P5  Control: the ESCAPE channels (`.sesslog_*` shape) render the same
      message on ONE line, so a line-based read is never ambiguous there.
  P6  Finding, not a prediction: the default formatter under RENDER
      (fileio / tools-output shape) closes its frame with ` }` at the END
      of the last body line rather than on its own line -- report the
      shape so the design can decide whether it needs the same rule.

Run: python tests/one-offs/thinking/poc_convo_frame_ambiguity.py
"""
from __future__ import annotations

import glob
import os
import re
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows console is cp1252; entries carry `←`
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / "hooks" / "scripts"))

from cclogger.formatters import format_for_channel  # noqa: E402
from cclogger.models import ChannelOptions, LogEntry, NewlinePolicy  # noqa: E402

TS = datetime(2026, 9, 3, 15, 0, 3)
CONVO_OPTS = ChannelOptions(verbosity="full", formatter="chat", newline_policy=NewlinePolicy.RENDER)
SESSLOG_OPTS = ChannelOptions()  # default formatter, ESCAPE
FILEIO_OPTS = ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.RENDER)

# The maintainer's message, brace structure intact (table rows trimmed).
MAINTAINER_MSG = (
    "re:{\n"
    " So \"show five lines of what this Bash command printed\" is not expressible in config today.\n"
    "}\n"
    "\n"
    "Okay we can create that as part of the lineup of things to do.\n"
    "\n"
    "Otherwise we are NOT going to push and release. ... we still had things to do:{\n"
    "re:{\n"
    "| Report-leg cursor bug | designed, not built |\n"
    "| Agent-id label mode   | designed, small, not built |\n"
    "}\n"
    "\n"
    "The main focus is that we need to make sure our logs are properly handling how untyped agents are being written.\n"
    "\n"
    "Then after that we want our \"sesslog-main\" which is essentially a simpler version of the sesslog."
)
BALANCED_MSG = MAINTAINER_MSG.replace("things to do:{", "things to do:")
ENTRYLIKE_MSG = (
    "Look at this line from the log:\n"
    "[[2026-09-03 14:03:12]] {AI:\n"
    "some quoted narration\n"
    "}\n"
    "Notice the frame."
)

START = re.compile(r"^\[\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\] \{[A-Za-z0-9:_/.-]+:$")


def render(msg: str, role: str, opts: ChannelOptions) -> str:
    entry = LogEntry(raw_content=msg, role=role, timestamp=TS, tool_name="UserPromptSubmit")
    return format_for_channel(entry, opts, "convo")


def brace_depth(text: str) -> int:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def col0_parse(text: str) -> tuple[int, int, list[str]]:
    """Column-0 rule: entries start at START lines, end at a bare `}` line.
    Returns (starts, ends, bodies)."""
    starts = ends = 0
    bodies: list[str] = []
    cur: list[str] | None = None
    for line in text.split("\n"):
        if START.match(line):
            starts += 1
            cur = []
        elif line == "}":
            ends += 1
            if cur is not None:
                bodies.append("\n".join(cur))
                cur = None
        elif cur is not None:
            cur.append(line)
    return starts, ends, bodies


def proposed_fix(rendered: str) -> str:
    """The design's E2: indent body lines two spaces, frame stays at column 0."""
    lines = rendered.split("\n")
    head, body, tail = lines[0], lines[1:-1], lines[-1]
    return "\n".join([head] + ["  " + b for b in body] + [tail])


def main() -> int:
    fails = 0

    print("== P1: real convo path, brace-matching read ==")
    r_bad = render(MAINTAINER_MSG, "user", CONVO_OPTS)
    r_ok = render(BALANCED_MSG, "user", CONVO_OPTS)
    d_bad, d_ok = brace_depth(r_bad), brace_depth(r_ok)
    print(f"  maintainer message: depth after last char = {d_bad}  (predicted != 0)")
    print(f"  control (balanced): depth after last char = {d_ok}  (predicted == 0)")
    p1 = d_bad != 0 and d_ok == 0
    print("  P1", "PASS" if p1 else "FAIL"); fails += not p1

    print("== P2: column-0 rule on a three-entry fixture (today's frame) ==")
    fixture = "\n".join([
        render(MAINTAINER_MSG, "user", CONVO_OPTS),
        render("A plain reply.", "ai", CONVO_OPTS),
        render(ENTRYLIKE_MSG, "user", CONVO_OPTS),
    ])
    s, e, bodies = col0_parse(fixture)
    print(f"  starts={s} ends={e} bodies_recovered={len(bodies)}  (3 entries written)")
    p2 = (s != 3) or (e != 3) or (len(bodies) != 3) or any(b not in (MAINTAINER_MSG, "A plain reply.", ENTRYLIKE_MSG) for b in bodies)
    print("  P2", "PASS (ambiguity reproduced)" if p2 else "FAIL (no ambiguity?)"); fails += not p2

    print("== P3: the proposed fix on the same fixture ==")
    fixed = "\n".join(proposed_fix(x) for x in [
        render(MAINTAINER_MSG, "user", CONVO_OPTS),
        render("A plain reply.", "ai", CONVO_OPTS),
        render(ENTRYLIKE_MSG, "user", CONVO_OPTS),
    ])
    s, e, bodies = col0_parse(fixed)
    deindented = ["\n".join(l[2:] if l.startswith("  ") else l for l in b.split("\n")) for b in bodies]
    roundtrip = deindented == [MAINTAINER_MSG, "A plain reply.", ENTRYLIKE_MSG]
    print(f"  starts={s} ends={e} bodies_recovered={len(bodies)} roundtrip={roundtrip}")
    p3 = s == 3 and e == 3 and len(bodies) == 3 and roundtrip
    print("  P3", "PASS" if p3 else "FAIL"); fails += not p3

    print("== P4: real population, this session's .convo_* ==")
    convo = sorted(glob.glob(os.path.expanduser("~/.claude/sesslogs/*112bad32*/.convo_*")))
    if convo:
        text = open(convo[0], encoding="utf-8", errors="replace").read()
        s, e, _ = col0_parse(text)
        body_col0_close = e - s
        print(f"  entry starts={s}  column-0 '}}' lines={e}  excess (body braces at column 0)={body_col0_close}")
        p4 = e > s
        print("  P4", "PASS (ambiguity present in the live record)" if p4 else "FAIL (no excess)"); fails += not p4
    else:
        print("  (no convo file found; P4 skipped)")

    print("== P5: control, ESCAPE channel shape ==")
    one = render(MAINTAINER_MSG, "user", SESSLOG_OPTS)
    print(f"  lines={one.count(chr(10)) + 1}  starts_with_frame={one.startswith('[[')}  ends_with_frame={one.endswith(' }')}")
    p5 = "\n" not in one
    print("  P5", "PASS" if p5 else "FAIL"); fails += not p5

    print("== P6: finding, default formatter under RENDER (fileio shape) ==")
    w = LogEntry(raw_content="line one\nline two {\n}", role="write", timestamp=TS, tool_name="Write",
                 summary='"C:/x/y.txt" ← {snippet} (3L)')
    shape = format_for_channel(w, FILEIO_OPTS, "fileio")
    print("  " + shape.replace("\n", "\n  "))
    print("  closing frame on its own line:", shape.split("\n")[-1] == "}")

    print("\nRESULT:", "ALL PREDICTIONS HELD" if fails == 0 else f"{fails} PREDICTION(S) FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
