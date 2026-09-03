"""Reproduction harness (2026-09-02): per-instance `.agents-<agent_id>` fan-out
and the hook slowdown that grows with the number of files in a session dir.

Observed in the wild (session ccd101d8, config-tool, 2026-08-21..09-02):
  * ~1,100 one-line `.agents-a<16hex>_*` files -- SubagentStop payloads that
    carry `agent_id` with an EMPTY `agent_type`; the #53 discriminator falls
    back to the id, so every such stop mints a new channel file.
  * hook durations: PostToolUse p50 5.7s / p90 48s, dense cluster at the 60s
    kill; ALL of it in the SessionLogger-init -> "Logged to" segment.

Two probes, both against an ISOLATED scratch CLAUDE_DIR (hooks run live from
this tree; never point this at the real ~/.claude):

  A. spam:    N SubagentStop events with distinct agent_id + agent_type ""
              -> count new `.agents-a*` files. Bug present iff count == N.
  B. timeout: seed the session dir with N synthetic id-files, time a
              PostToolUse per rung of an N ladder, then cProfile the top
              rung so the hot function is named, not guessed.

Usage:
  python repro_agent_spam_and_timeout.py            # both probes, ladder 0/100/400/1000
  python repro_agent_spam_and_timeout.py --ladder 0,200 --spam 10
  python repro_agent_spam_and_timeout.py --keep     # leave the scratch dir for inspection
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "ccd10000-0000-4000-8000-00000000d1d8"
USER = "repro"


def _env(claude_dir: Path) -> dict:
    claude_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLAUDE_DIR"] = str(claude_dir)           # paths.claude_dir(): CLAUDE_DIR wins
    env.pop("CLAUDE_CONFIG_DIR", None)
    env["USERNAME"] = USER
    env["USER"] = USER
    env["PYTHONUTF8"] = "1"
    return env


def _base(transcript: Path) -> dict:
    return {
        "session_id": GUID,
        "transcript_path": str(transcript),
        "cwd": str(REPO),
        "permission_mode": "default",
    }


def _run(env: dict, payload: dict, profile: bool = False, timeout: float = 300) -> tuple[float, str]:
    cmd = [sys.executable]
    if profile:
        cmd += ["-m", "cProfile", "-s", "cumtime"]
    cmd.append(str(HOOK))
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env, timeout=timeout)
    dt = time.perf_counter() - t0
    if proc.returncode != 0:
        print("  hook rc", proc.returncode, proc.stderr.decode(errors="replace")[:400])
    return dt, proc.stdout.decode(errors="replace")


def _session_dir(sesslogs: Path) -> Path:
    dirs = [d for d in sesslogs.iterdir() if d.is_dir() and GUID in d.name]
    assert len(dirs) == 1, f"expected one session dir, got {dirs}"
    return dirs[0]


def _agent_files(d: Path) -> list[Path]:
    return sorted(p for p in d.iterdir() if p.name.startswith(".agents-a") and p.is_file())


def probe_spam(claude_dir: Path, n: int) -> int:
    print(f"\n== Probe A: {n} SubagentStop events, agent_type='' + distinct agent_id ==")
    env = _env(claude_dir)
    transcript = claude_dir / "t.jsonl"
    transcript.write_text("", encoding="utf-8")
    base = _base(transcript)
    _run(env, dict(base, hook_event_name="SessionStart", source="startup"))
    _run(env, dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                   tool_input={"command": "echo warm"},
                   tool_response={"stdout": "warm", "stderr": "", "interrupted": False}))
    sdir = _session_dir(claude_dir / "sesslogs")
    before = len(_agent_files(sdir))
    for i in range(n):
        aid = f"a{i:016x}"
        _run(env, dict(base, hook_event_name="SubagentStop", agent_id=aid, agent_type="",
                       stop_hook_active=False, agent_transcript_path=str(claude_dir / "missing.jsonl"),
                       last_assistant_message=f"Share the attribution DWP with box-{i} so it's on the same page"))
    after = len(_agent_files(sdir))
    made = after - before
    print(f"  new .agents-a* files: {made}  (bug present iff == {n})")
    # control: same shape but NO agent_id -> must not mint anything
    _run(env, dict(base, hook_event_name="SubagentStop", agent_type="",
                   stop_hook_active=False, last_assistant_message="control: no agent_id"))
    print(f"  control (no agent_id) minted: {len(_agent_files(sdir)) - after}")
    return made


def probe_timeout(claude_dir: Path, ladder: list[int], reps: int) -> None:
    print(f"\n== Probe B: PostToolUse wall time vs number of id-files in the session dir ==")
    env = _env(claude_dir)
    transcript = claude_dir / "t.jsonl"
    transcript.write_text("", encoding="utf-8")
    base = _base(transcript)
    tool = dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                tool_input={"command": "echo x"},
                tool_response={"stdout": "x", "stderr": "", "interrupted": False})
    _run(env, dict(base, hook_event_name="SessionStart", source="startup"))
    _run(env, tool)
    sdir = _session_dir(claude_dir / "sesslogs")
    # Learn the live naming tail from a real file: ".<base>_<tail>"
    real = next(p for p in sdir.iterdir() if p.name.startswith(".sesslog"))
    tail = real.name.split("_", 1)[1]
    print(f"  session dir: {sdir.name}\n  naming tail: _{tail}")
    have = 0
    results = []
    for n in ladder:
        while have < n:
            (sdir / f".agents-a{have:016x}_{tail}").write_text(
                f"[[2026-09-02 00:00:00]] {{AGENT:a{have:016x}: seed }}\n", encoding="utf-8")
            have += 1
        times = [_run(env, tool)[0] for _ in range(reps)]
        med = statistics.median(times)
        results.append((n, med))
        print(f"  files={n:5d}  PostToolUse median={med:7.3f}s  (runs: {', '.join(f'{t:.2f}' for t in times)})")
    if len(results) >= 2 and results[0][1] > 0:
        n0, t0 = results[1]
        n1, t1 = results[-1]
        if n0 and t0 > 0:
            print(f"  growth: {n1/n0:.1f}x files -> {t1/t0:.1f}x time  "
                  f"({'super-linear' if t1/t0 > 1.5*(n1/n0) else 'about linear or better'})")
    print("\n  -- cProfile at top rung (cumtime, top 28 lines) --")
    _, out = _run(env, tool, profile=True)
    lines = out.splitlines()
    start = next((i for i, l in enumerate(lines) if "cumulative" in l), 0)
    for l in lines[start:start + 28]:
        print("  " + l[:150])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ladder", default="0,100,400,1000")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--spam", type=int, default=5)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--only", choices=["spam", "timeout"], default=None)
    a = ap.parse_args(argv)
    ladder = [int(x) for x in a.ladder.split(",")]
    root = Path(tempfile.mkdtemp(prefix="csl-repro-"))
    print(f"scratch CLAUDE_DIR root: {root}")
    try:
        if a.only in (None, "spam"):
            probe_spam(root / "spam", a.spam)
        if a.only in (None, "timeout"):
            probe_timeout(root / "timeout", ladder, a.reps)
    finally:
        if a.keep:
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
