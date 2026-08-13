"""Spike driver (2026-08-13): validated the #53 emitter/collector design red-green.

Graduated from scratchpad per one-offs/thinking convention -- this is a THINKING
artifact that validated the DWP recommendation before implementation, not a
regression test. The real coverage ships with #53 (AC-1..AC-9 in the DWP:
2026-08-13__10-42-19__issue-53-agent-context-routing-design.md, project-private).

Result on unmodified d9f6641 + ~15-line throwaway patch in an isolated copy:
5/5 PASS -- collection works end-to-end through the real hook subprocess;
agent_id discriminator refuses the --agent shape; additivity holds; and the
run live-demonstrated Windows case-coalescence of .agents-Explore_/.agents-explore_
(the normalize_subtype rationale).

Fixture facts learned (encode in real tests): the dispatch tool is named
"Agent" (not "Task") in current Claude Code; split semantics write collected
entries to BOTH the base .agents_ and the .agents-<type>_ sibling.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
import tempfile
SPIKE = Path(tempfile.mkdtemp(prefix="spike53_"))
GUID = "5p1ke000-53aa-4bbb-8ccc-agentroute001"
USER = "SpikeUser"


def make_copy(tag: str) -> Path:
    dst = SPIKE / f"copy_{tag}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    shutil.copytree(REPO / "hooks", dst / "hooks")
    shutil.copy(REPO / "version.py", dst / "version.py")
    return dst


def events(transcript: Path) -> list:
    base = {
        "session_id": GUID,
        "transcript_path": str(transcript),
        "cwd": "/spike-agent-routing",
        "permission_mode": "default",
    }
    evs = [dict(base, hook_event_name="SessionStart", source="startup")]
    # 1) Task dispatch (main session -- no agent_id/agent_type at top level)
    evs.append(dict(
        base, hook_event_name="PostToolUse", tool_name="Agent",
        tool_input={"subagent_type": "Explore", "prompt": "spike probe prompt",
                    "description": "spike probe"},
        tool_response={"status": "launched"},
    ))
    # 2-4) Internal calls: agent_id + agent_type present (true subagent shape)
    for i in range(3):
        evs.append(dict(
            base, hook_event_name="PostToolUse", tool_name="Bash",
            agent_id="spikeagent0001", agent_type="Explore",
            tool_input={"command": f"echo inner-call-{i}"},
            tool_response={"stdout": f"inner-call-{i}", "stderr": "",
                           "interrupted": False},
        ))
    # 5) The --agent shape: agent_type WITHOUT agent_id -> must NOT collect
    evs.append(dict(
        base, hook_event_name="PostToolUse", tool_name="Bash",
        agent_type="Explore",
        tool_input={"command": "echo main-thread-of-agent-session"},
        tool_response={"stdout": "x", "stderr": "", "interrupted": False},
    ))
    # 6) SubagentStop (informational in spike -- report leg)
    evs.append(dict(
        base, hook_event_name="SubagentStop", agent_id="spikeagent0001",
        agent_type="Explore", stop_hook_active=False,
        agent_transcript_path=str(transcript),
        last_assistant_message="SPIKE-REPORT: findings text here",
    ))
    return evs


def drive(copy_dir: Path, home: Path) -> None:
    hook = copy_dir / "hooks" / "scripts" / "log-command.py"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["USERNAME"] = USER
    env["USER"] = USER
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR", "TMUX"):
        env.pop(k, None)
    site = str(Path.home() / ".local" / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
    env["PYTHONPATH"] = site + os.pathsep + env.get("PYTHONPATH", "")
    transcript = home / "fake-transcript.jsonl"
    transcript.write_text('{"type":"user","message":{"content":"spike"}}\n',
                          encoding="utf-8")
    for ev in events(transcript):
        proc = subprocess.run([sys.executable, str(hook)],
                              input=json.dumps(ev).encode("utf-8"),
                              capture_output=True, env=env, timeout=30)
        assert proc.returncode == 0, proc.stderr.decode()[:800]


def inspect(home: Path, label: str) -> dict:
    sess_dirs = list((home / ".claude" / "sesslogs").glob("*"))
    result = {"label": label, "agents_files": {}, "sesslog_attributed": 0,
              "agents_bash_entries": 0, "agents_dispatch_entries": 0}
    for d in sess_dirs:
        for f in sorted(d.glob(".agents*")):
            text = f.read_text(encoding="utf-8", errors="replace")
            result["agents_files"][f.name.split("__")[0]] = {
                "bytes": len(text.encode()),
                "dispatch": text.count("{Agent"),
                "bash": text.count("{Bash"),
                "has_no_id_call": "main-thread-of-agent-session" in text,
            }
            result["agents_bash_entries"] += text.count("{Bash")
            result["agents_dispatch_entries"] += text.count("{Agent")
        for f in d.glob(".sesslog*"):
            text = f.read_text(encoding="utf-8", errors="replace")
            result["sesslog_attributed"] = text.count("|Explore")
    return result


PATCH_ROUTE_OLD = """        # Get channels to write to based on routing config
        channels = self._get_channels_for_tool(tool_name, tool_category)"""
PATCH_ROUTE_NEW = """        # Get channels to write to based on routing config
        channels = self._get_channels_for_tool(tool_name, tool_category)
        # SPIKE(#53): collect agent-context entries into agents channel
        if (raw_json or {}).get("agent_id") and (raw_json or {}).get("agent_type"):
            if "agents" not in channels:
                channels = list(channels) + ["agents"]"""

PATCH_SUB_OLD = """            subtype_channel = f"{base_channel}-{subtype}\""""
PATCH_SUB_NEW = """            _sub = subtype
            # SPIKE(#53): context-collected entries split by agent type
            if base_channel == "agents" and (raw_json or {}).get("agent_id"):
                _ac = (raw_json or {}).get("agent_type")
                if _ac:
                    _sub = str(_ac).lower()
            subtype_channel = f"{base_channel}-{_sub}\""""


def apply_patch(copy_dir: Path) -> None:
    lg = copy_dir / "hooks" / "scripts" / "cclogger" / "logger.py"
    src = lg.read_text(encoding="utf-8")
    assert PATCH_ROUTE_OLD in src, "route patch anchor missing"
    assert PATCH_SUB_OLD in src, "subtype patch anchor missing"
    src = src.replace(PATCH_ROUTE_OLD, PATCH_ROUTE_NEW)
    src = src.replace(PATCH_SUB_OLD, PATCH_SUB_NEW)
    lg.write_text(src, encoding="utf-8")


def main():
    print("=== RED: unmodified copy ===")
    red_copy = make_copy("red")
    red_home = SPIKE / "home_red"
    if red_home.exists():
        shutil.rmtree(red_home)
    red_home.mkdir()
    drive(red_copy, red_home)
    red = inspect(red_home, "red")
    print(json.dumps(red, indent=2))

    print("=== GREEN: patched copy ===")
    green_copy = make_copy("green")
    apply_patch(green_copy)
    green_home = SPIKE / "home_green"
    if green_home.exists():
        shutil.rmtree(green_home)
    green_home.mkdir()
    drive(green_copy, green_home)
    green = inspect(green_home, "green")
    print(json.dumps(green, indent=2))

    print("=== VERDICT ===")
    checks = [
        ("RED baseline: agents files carry dispatch only (0 Bash)",
         red["agents_bash_entries"] == 0 and red["agents_dispatch_entries"] >= 1),
        ("GREEN: 3 gated calls in base .agents_ AND 3 in the subtype sibling (split semantics)",
         green["agents_bash_entries"] == 6
         and any("xplore" in k.lower() and v["bash"] == 3
                 for k, v in green["agents_files"].items())),
        ("GREEN: dispatch still present in agents files",
         green["agents_dispatch_entries"] >= 1),
        ("GREEN: agent_id-less (--agent shape) call NOT collected",
         not any(v["has_no_id_call"] for v in green["agents_files"].values())),
        ("Additivity: sesslog attribution unchanged red->green",
         red["sesslog_attributed"] == green["sesslog_attributed"] > 0),
    ]
    ok = True
    for name, passed in checks:
        print(("PASS  " if passed else "FAIL  ") + name)
        ok = ok and passed
    print("SPIKE:", "VALIDATED" if ok else "FALSIFIED")


if __name__ == "__main__":
    main()
