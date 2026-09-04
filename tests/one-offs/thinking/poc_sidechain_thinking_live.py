"""PoC (2026-09-04): does the sidechain reader capture an agent's THINKING
from a real subagent transcript on this box?

Why: this session's own logs show every typed-agent stop as
`stopped (0 narration, 0 thinking, report)` while the agent's transcript on
disk demonstrably holds a thinking block. Either the reader skips thinking,
or the transcript shape differs from what it expects, or the file was not
flushed when the hook ran. This settles which, on the real population.

PREDICTION (registered before running): the reader returns the text block
but no thinking block, because the sidechain's thinking blocks carry their
text under a key the extractor does not read. Control arm: the same
extractor on the MAIN transcript, where thinking capture is known to work
(13 {THINK: ...} entries are in this session's sesslog).

PASS = the probe reproduces 0 thinking from a file that contains thinking.
FAIL = the probe returns the thinking, meaning the live gap was timing.

RESULT (2026-09-04, eight sidechain files, 5 thinking blocks on disk, 0
read -- prediction held, but the cause was NOT the one predicted). The
extractor is correct and the block shape is the expected one
(`['signature', 'thinking', 'type']`); the `thinking` value is the empty
string in every case. Claude Code persists a subagent's thinking blocks
with the text stripped out -- the signature is kept, the words are not.
So the reader has nothing to record, `stopped (N narration, 0 thinking,
report)` is honest, and writing an empty `{AGENT-THINK:...}` line per
block would be noise. Main-thread thinking is unaffected: it carries its
text and is captured (13 `{THINK: ...}` entries in this session).

Consequences taken: the CHANGELOG states the caveat, the release
checklist tells the tester that zero `{AGENT-THINK:...}` lines is not a
failure, and `test_blank_blocks_and_signature_ignored` in
tests/one-offs/test_sidechain_reader.py now pins the exact live shape
(`"thinking": ""` beside a signature) rather than only a whitespace one.

Run: python tests/one-offs/thinking/poc_sidechain_thinking_live.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "hooks" / "scripts"))

CLAUDE = Path.home() / ".claude"
SESSION = "112bad32-b3fb-4d3a-abc7-130c2da48a21"


def _raw_block_shapes(path: Path) -> dict:
    """What the file actually holds, by block type -> the keys of one block."""
    shapes: dict = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                shapes.setdefault(block.get("type"), sorted(block.keys()))
    return shapes


def main() -> int:
    from cclogger.conversation import _extract_blocks_from_assistant_entry

    subagents = CLAUDE / "projects" / "C--code-claude-projects-claude-session-logger-github" / SESSION / "subagents"
    files = sorted(subagents.glob("agent-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("no sidechain transcripts found; nothing to probe")
        return 2

    print(f"{'file':<28} {'raw thinking':>12} {'raw text':>9} {'read thinking':>14} {'read text':>10}")
    totals = {"raw_thinking": 0, "read_thinking": 0}
    for path in files[:8]:
        raw_thinking = raw_text = 0
        read_thinking = read_text = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "thinking":
                            raw_thinking += 1
                        elif block.get("type") == "text":
                            raw_text += 1
            for kind, _text in _extract_blocks_from_assistant_entry(entry):
                if kind == "thinking":
                    read_thinking += 1
                elif kind == "text":
                    read_text += 1
        totals["raw_thinking"] += raw_thinking
        totals["read_thinking"] += read_thinking
        print(f"{path.name[:28]:<28} {raw_thinking:>12} {raw_text:>9} {read_thinking:>14} {read_text:>10}")

    print()
    shapes = _raw_block_shapes(files[0])
    print(f"block shapes in {files[0].name}:")
    for block_type, keys in shapes.items():
        print(f"  {block_type}: {keys}")

    print()
    if totals["raw_thinking"] and not totals["read_thinking"]:
        print(f"PASS (prediction held): {totals['raw_thinking']} thinking blocks on disk, 0 read")
        return 1
    if totals["raw_thinking"] and totals["read_thinking"]:
        print(f"FAIL (prediction wrong): {totals['read_thinking']} of {totals['raw_thinking']} thinking blocks read "
              "-- the extractor works, so the live gap was timing or the cursor")
        return 0
    print("INCONCLUSIVE: no thinking blocks on disk in the sampled files")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
