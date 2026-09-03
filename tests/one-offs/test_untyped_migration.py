"""One-time migration of legacy per-instance untyped files (unit U4, 2026-09-02
incident): `.agents-a<16hex>_*` files minted by v0.3.11..v0.3.15 are merged,
in timestamp order, into the single untyped feed (`.agents-untyped_*`), and
the originals are moved -- never deleted -- to `baks/untyped-<date>/` with a
MANIFEST. Sentinel-gated like the overflow and orphan sweeps; runs on the
first event of a run from SessionLogger.__init__.

Design: 2026-09-02__16-03-52__dev-workflow-process__untyped-subagent-bucketing-and-reconciliation-gating.md
(project-private; Addendum 3, AC-7). Blast radius when written: 25 of 528
session directories, 1,003 files.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "d1a90000-0902-4bbb-8ccc-0000000000d4"
USER = "miguser"
SHELL = "bash.exe"
NAME = "migrated-session"
TAIL = f"{SHELL}__{NAME}__{GUID}_{USER}.log"
ID_FILE = re.compile(r"^\.agents-a[0-9a-f]{16}_")


def _legacy(d: Path, i: int, ts: datetime, lines: int = 1) -> Path:
    """One legacy id-file: `lines` entries, the first at `ts`, continuation
    lines on the odd entries to exercise multi-line bodies."""
    aid = f"a{i:016x}"
    p = d / f".agents-{aid}_{TAIL}"
    body = []
    for k in range(lines):
        t = (ts + timedelta(seconds=k)).strftime("%Y-%m-%d %H:%M:%S")
        body.append(f"[[{t}]] {{AGENT:{aid}: LEGACY-{i:04d}-{k} verifying step {k} }}")
        if k % 2 == 1:
            body.append("continuation line for the same entry")
    p.write_text("\n".join(body) + "\n", encoding="utf-8")
    return p


def _seed(d: Path, n: int, seed: int = 7) -> list[str]:
    """Seed n legacy files with shuffled timestamps; return the expected
    chronological order of first-line markers."""
    rng = random.Random(seed)
    base = datetime(2026, 8, 21, 2, 0, 0)
    stamps = [base + timedelta(minutes=3 * i) for i in range(n)]
    rng.shuffle(stamps)
    for i, ts in enumerate(stamps):
        _legacy(d, i, ts, lines=3 if i % 10 == 0 else 1)
    order = sorted(range(n), key=lambda i: stamps[i])
    return [f"LEGACY-{i:04d}-0" for i in order]


def _feed(d: Path) -> Path:
    feeds = list(d.glob(".agents-untyped_*"))
    assert len(feeds) == 1, [p.name for p in d.iterdir()]
    return feeds[0]


class TestMigrateUntypedAgentFiles:
    def test_merges_in_timestamp_order_and_moves_originals(self, tmp_path):
        from cclogger.file_io import UNTYPED_MIGRATION_SENTINEL, migrate_untyped_agent_files
        expected = _seed(tmp_path, 300)
        moved = migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        assert moved == 300
        # root: no id-files left; exactly one feed; sentinel dropped
        assert [p.name for p in tmp_path.iterdir() if ID_FILE.match(p.name)] == []
        feed = _feed(tmp_path)
        text = feed.read_text(encoding="utf-8")
        markers = re.findall(r"LEGACY-(\d{4})-0 ", text)
        assert [f"LEGACY-{m}-0" for m in markers] == expected
        # multi-line entries survive intact (continuation lines follow their entry)
        assert "continuation line for the same entry" in text
        assert text.count("[[") == 300 + 2 * 30           # 30 files had 3 entries
        sentinel = tmp_path / UNTYPED_MIGRATION_SENTINEL
        assert sentinel.exists() and "absorbed=300" in sentinel.read_text(encoding="utf-8")
        # originals in baks/untyped-<date>/ with a manifest
        baks = list((tmp_path / "baks").glob("untyped-*"))
        assert len(baks) == 1, baks
        originals = [p for p in baks[0].iterdir() if ID_FILE.match(p.name)]
        assert len(originals) == 300
        manifest = (baks[0] / "MANIFEST.txt").read_text(encoding="utf-8")
        assert manifest.count(".agents-a") == 300

    def test_idempotent_second_run_is_a_no_op(self, tmp_path):
        from cclogger.file_io import migrate_untyped_agent_files
        _seed(tmp_path, 20)
        assert migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER) == 20
        before = sorted(p.name for p in tmp_path.rglob("*"))
        feed_bytes = _feed(tmp_path).read_bytes()
        assert migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER) == 0
        assert sorted(p.name for p in tmp_path.rglob("*")) == before
        assert _feed(tmp_path).read_bytes() == feed_bytes

    def test_existing_feed_keeps_chronology(self, tmp_path):
        """A live session already writing to the feed: legacy entries are
        older, so they must land BEFORE the existing lines."""
        from cclogger.file_io import migrate_untyped_agent_files
        _seed(tmp_path, 5)
        feed = tmp_path / f".agents-untyped_{TAIL}"
        feed.write_text("[[2026-09-03 01:00:00]] {AGENT:untyped/a00000000000beef: NEW-LINE }\n", encoding="utf-8")
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = feed.read_text(encoding="utf-8")
        assert text.index("LEGACY-") < text.index("NEW-LINE")
        assert text.rstrip().endswith("NEW-LINE }")

    def test_nothing_to_migrate_still_drops_sentinel(self, tmp_path):
        from cclogger.file_io import UNTYPED_MIGRATION_SENTINEL, migrate_untyped_agent_files
        (tmp_path / f".sesslog_{TAIL}").write_text("x\n", encoding="utf-8")
        assert migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER) == 0
        assert (tmp_path / UNTYPED_MIGRATION_SENTINEL).exists()
        assert list(tmp_path.glob(".agents-untyped_*")) == []

    def test_pre_existing_baks_subdir_untouched(self, tmp_path):
        """ccd101d8's manual move (baks/untyped-agents-2026-09-02/) must survive."""
        from cclogger.file_io import migrate_untyped_agent_files
        manual = tmp_path / "baks" / "untyped-agents-2026-09-02"
        manual.mkdir(parents=True)
        (manual / f".agents-a00000000000dead_{TAIL}").write_text("manual\n", encoding="utf-8")
        (manual / "MANIFEST.txt").write_text("manual manifest\n", encoding="utf-8")
        _seed(tmp_path, 3)
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        assert (manual / f".agents-a00000000000dead_{TAIL}").read_text(encoding="utf-8") == "manual\n"
        assert (manual / "MANIFEST.txt").read_text(encoding="utf-8") == "manual manifest\n"
        assert "dead" not in _feed(tmp_path).read_text(encoding="utf-8")

    def test_unnamed_session_form(self, tmp_path):
        from cclogger.file_io import migrate_untyped_agent_files
        p = tmp_path / f".agents-a000000000000aaaa_{SHELL}_{GUID}_{USER}.log"
        p.write_text("[[2026-08-21 02:00:00]] {AGENT:a000000000000aaaa: UNNAMED-FORM }\n", encoding="utf-8")
        assert migrate_untyped_agent_files(tmp_path, GUID, None, SHELL, USER) == 1
        feed = tmp_path / f".agents-untyped_{SHELL}_{GUID}_{USER}.log"
        assert feed.exists() and "UNNAMED-FORM" in feed.read_text(encoding="utf-8")

    # -- survivors of the first mutation sweep, each pinned by its own test --

    def test_equal_stamps_keep_filename_order(self, tmp_path):
        """Kills M3 (sorted() dropped): two files with the SAME stamp must
        merge in filename order, deterministically."""
        from cclogger.file_io import migrate_untyped_agent_files
        ts = datetime(2026, 8, 21, 3, 0, 0)
        _legacy(tmp_path, 0xB, ts)          # ...000b sorts after ...000a
        _legacy(tmp_path, 0xA, ts)
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = _feed(tmp_path).read_text(encoding="utf-8")
        assert text.index("LEGACY-0010-0") < text.index("LEGACY-0011-0")

    def test_order_does_not_depend_on_directory_listing_order(self, tmp_path, monkeypatch):
        """Kills M3 (sorted() dropped) even on filesystems that already list
        names in order (NTFS): force a reversed listing; equal-stamp entries
        must still merge by filename."""
        import cclogger.reconciliation as rec
        real = rec.list_session_dir
        monkeypatch.setattr(rec, "list_session_dir", lambda d: list(reversed(real(d))))
        from cclogger.file_io import migrate_untyped_agent_files
        ts = datetime(2026, 8, 21, 3, 30, 0)
        for i in (0xC, 0xA, 0xB):
            _legacy(tmp_path, i, ts)
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = _feed(tmp_path).read_text(encoding="utf-8")
        assert text.index("LEGACY-0010-0") < text.index("LEGACY-0011-0") < text.index("LEGACY-0012-0")

    def test_interleaved_stamps_across_files_merge_per_entry(self, tmp_path):
        """Kills M5 (entry boundary or -> and): a file's second entry must
        sort on its OWN stamp, not travel with the file's first entry."""
        from cclogger.file_io import migrate_untyped_agent_files
        t0 = datetime(2026, 8, 21, 4, 0, 0)
        a = tmp_path / f".agents-a00000000000000aa_{TAIL}"
        a.write_text(f"[[{t0:%Y-%m-%d %H:%M:%S}]] {{AGENT:a00000000000000aa: A-FIRST }}\n"
                     f"[[{t0 + timedelta(minutes=10):%Y-%m-%d %H:%M:%S}]] {{AGENT:a00000000000000aa: A-SECOND }}\n",
                     encoding="utf-8")
        b = tmp_path / f".agents-a00000000000000bb_{TAIL}"
        b.write_text(f"[[{t0 + timedelta(minutes=5):%Y-%m-%d %H:%M:%S}]] {{AGENT:a00000000000000bb: B-ONLY }}\n",
                     encoding="utf-8")
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = _feed(tmp_path).read_text(encoding="utf-8")
        assert text.index("A-FIRST") < text.index("B-ONLY") < text.index("A-SECOND")

    def test_unreadable_file_is_left_in_place_not_moved(self, tmp_path, monkeypatch):
        """Kills M6 (continue dropped): a file that cannot be read must stay in
        the root and contribute nothing to the feed."""
        from cclogger.file_io import migrate_untyped_agent_files
        from pathlib import Path as _P
        good = _legacy(tmp_path, 1, datetime(2026, 8, 21, 5, 0, 0))
        bad = _legacy(tmp_path, 2, datetime(2026, 8, 21, 5, 1, 0))
        real = _P.read_text

        def flaky(self, *a, **k):
            if self.name == bad.name:
                raise OSError("simulated unreadable file")
            return real(self, *a, **k)
        monkeypatch.setattr(_P, "read_text", flaky)
        moved = migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        assert moved == 1
        assert bad.exists() and not good.exists()
        assert "LEGACY-0002" not in _feed(tmp_path).read_text(encoding="utf-8")

    def test_banner_leads_the_migrated_block(self, tmp_path):
        """Kills M7 (banner after the entries)."""
        from cclogger.file_io import migrate_untyped_agent_files
        _seed(tmp_path, 3)
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = _feed(tmp_path).read_text(encoding="utf-8")
        # 3 files, the first of which carries 3 entries (see _seed) -> 5 entries
        assert text.startswith("═══ MIGRATED 5 legacy untyped entries from 3 per-instance file(s)")
        assert text.index("═══") < text.index("LEGACY-")

    def test_repeated_collisions_get_distinct_suffixes(self, tmp_path):
        """Kills M8 (collision loop -> single if): the same legacy name moved
        three times into one baks/<date>/ dir needs `.1` AND `.2`."""
        from cclogger.file_io import UNTYPED_MIGRATION_SENTINEL, migrate_untyped_agent_files
        for _round in range(3):
            _legacy(tmp_path, 7, datetime(2026, 8, 21, 6, 0, 0))
            (tmp_path / UNTYPED_MIGRATION_SENTINEL).unlink(missing_ok=True)
            assert migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER) == 1
        baks = next(iter((tmp_path / "baks").glob("untyped-*")))
        names = sorted(p.name for p in baks.iterdir())
        stem = f".agents-a0000000000000007_{TAIL}"
        assert stem in names and f"{stem}.1" in names and f"{stem}.2" in names, names

    def test_sentinel_body_describes_this_sweep(self, tmp_path):
        """Kills M9 (wrong sentinel kind)."""
        from cclogger.file_io import UNTYPED_MIGRATION_SENTINEL, migrate_untyped_agent_files
        _seed(tmp_path, 2)
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        body = (tmp_path / UNTYPED_MIGRATION_SENTINEL).read_text(encoding="utf-8")
        assert "untyped-agent migration marker" in body and "absorbed=2" in body

    def test_embedded_stamp_in_a_continuation_line_does_not_split(self, tmp_path):
        """Kills M10 (stamp regex loses ^): a continuation line that merely
        CONTAINS `[[stamp]]` text stays attached to its entry."""
        from cclogger.file_io import migrate_untyped_agent_files
        p = tmp_path / f".agents-a00000000000000cc_{TAIL}"
        p.write_text("[[2026-08-21 07:00:00]] {AGENT:a00000000000000cc: quoting a log line\n"
                     "  it said [[2026-01-01 00:00:00]] earlier -- still the same entry }\n",
                     encoding="utf-8")
        migrate_untyped_agent_files(tmp_path, GUID, NAME, SHELL, USER)
        text = _feed(tmp_path).read_text(encoding="utf-8")
        assert "MIGRATED 1 legacy untyped entries" in text
        assert "quoting a log line\n  it said [[2026-01-01 00:00:00]] earlier" in text


# ============================================================================
# End to end: the hook migrates on the first event of a run
# ============================================================================

def _drive(home: Path, events: list) -> None:
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
    for ev in events:
        proc = subprocess.run([sys.executable, str(HOOK_SCRIPT)],
                              input=json.dumps(ev).encode("utf-8"),
                              capture_output=True, env=env, timeout=60)
        assert proc.returncode == 0, proc.stderr.decode()[:800]


class TestHookMigration:
    def test_first_event_of_a_run_migrates_legacy_files(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        base = {"session_id": GUID, "transcript_path": str(transcript),
                "cwd": str(REPO), "permission_mode": "default"}
        tool = dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                    tool_input={"command": "echo x"},
                    tool_response={"stdout": "x", "stderr": "", "interrupted": False})
        _drive(home, [dict(base, hook_event_name="SessionStart", source="startup"), tool])
        d = next(p for p in (home / ".claude" / "sesslogs").iterdir() if GUID in p.name)
        tail = next(iter(d.glob(".sesslog_*"))).name.split("_", 1)[1]
        # Model the real case: a directory written by v0.3.11..v0.3.15 has
        # legacy id-files and NO migration sentinel yet. (The first run above
        # already stamped this fresh dir, so remove the stamp -- the sentinel
        # is documented as safe to delete / rerun.)
        from cclogger.file_io import UNTYPED_MIGRATION_SENTINEL
        (d / UNTYPED_MIGRATION_SENTINEL).unlink()
        for i in range(40):
            (d / f".agents-a{i:016x}_{tail}").write_text(
                f"[[2026-08-21 02:{i:02d}:00]] {{AGENT:a{i:016x}: LEGACY-{i} }}\n", encoding="utf-8")
        # new run -> first event migrates
        _drive(home, [dict(base, hook_event_name="SessionStart", source="resume"), tool])
        assert [p.name for p in d.iterdir() if ID_FILE.match(p.name)] == []
        feed = next(iter(d.glob(".agents-untyped_*")))
        assert feed.read_text(encoding="utf-8").count("LEGACY-") == 40
        baks = list((d / "baks").glob("untyped-*"))
        assert len(baks) == 1 and len(list(baks[0].glob(".agents-a*"))) == 40
