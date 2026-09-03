"""Entry framing: the frame's braces always match, the body stays verbatim.

Every channel entry is framed as `{LABEL: body }` (one line) or, in a
`render` channel, `{LABEL:` / body / `}`. The maintainer walks a log with
the editor's brace jump (vim `%`, VS Code bracket matching) from an
entry's first `{` to its last `}` -- and editors count EVERY brace in a
plain-text file, including the ones inside a body. The body is the thing
being recorded, so it is never altered; the balance is restored OUTSIDE
the frame (design 2026-09-03, Addendum 4):

  * for every `{` in the body with no partner, one `}` is appended after
    the frame's closing brace -- a body with two unclosed braces ends
    `}}}`;
  * for every `}` in the body with no partner, one `{` is inserted after
    the frame's opening brace -- `{{USER:`.

The frame's own braces stay the outermost pair, so the jump from the
first `{` lands on the last `}` in every channel, and the number of extra
braces says how many strays the body holds without guessing where they
belong. Balanced bodies get no extra braces. Trigger: a prompt that
quoted a log entry verbatim -- no choice of delimiter can survive that,
and 24 such body braces sat unmatched in one live `.convo_*`.

Rejected on the way here (kept in dz git-snapshots 1b723cc5d01b and
b465e11a8e8d): backslash-escaping strays (editors ignore escapes in plain
text), completing strays in place as `{}` (alters recorded content --
`dict = {` is not `dict = {}`), and a per-channel continuation indent
(presentation only; indents fight a narrow terminal, the main use case).

Self-contained by design (dazzle-loglib export candidate): pure string
functions, no I/O, no config.
"""
from __future__ import annotations


def stray_counts(text: str) -> tuple[int, int]:
    """Return (unmatched_open, unmatched_close): how many `{` in `text` have
    no `}` after them, and how many `}` have no `{` before them."""
    if "{" not in text and "}" not in text:
        return (0, 0)
    depth = 0
    unmatched_close = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
            else:
                unmatched_close += 1
    return (depth, unmatched_close)


_TS_PREFIX_END = "]] "


def pad_frame(entry: str) -> str:
    """Frame integrity, applied once to a fully assembled entry.

    The entry is `[[ts]] {...}` optionally followed by a pwd part
    ` ["..."]`. The body between the frame's `{` and `}` is left verbatim;
    for every `{` in the body with no partner, one `}` is appended after
    the frame's `}`, and for every `}` with no partner, one `{` is
    inserted after the frame's `{`. Entries that do not have the frame
    shape (markers, plain strings, anything with other text after the
    frame) are returned unchanged."""
    if "{" not in entry:
        return entry
    start = entry.find(_TS_PREFIX_END)
    start = start + len(_TS_PREFIX_END) if start >= 0 else 0
    if start >= len(entry) or entry[start] != "{":
        return entry
    close = entry.rfind("}")
    if close <= start:
        return entry
    tail = entry[close + 1:]
    if tail and not (tail.startswith(' ["') and tail.endswith('"]')):
        return entry  # something other than a pwd part follows the frame
    body = entry[start + 1:close]
    unmatched_open, unmatched_close = stray_counts(body)
    if not unmatched_open and not unmatched_close:
        return entry
    return (
        entry[:start] + "{" + "{" * unmatched_close + body + "}" + "}" * unmatched_open + tail
    )


def frame_is_matched(entry: str) -> bool:
    """Reader-side check used by tests and probes, counting braces the way
    an editor does (every brace, no escapes): over a rendered entry the
    depth never returns to zero before the final `}`, never goes negative,
    and is zero at the end -- the entry's first `{` pairs with its last `}`.
    A pwd part after the frame is ignored."""
    close = entry.rfind("}")
    if close < 0:
        return False
    depth = 0
    for i, ch in enumerate(entry[: close + 1]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and i != close:
                return False
    return depth == 0
