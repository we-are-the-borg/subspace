"""Synthetic checks of the Claude Code capture driver; never starts Claude Code."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CAPTURE = Path(__file__).resolve().parents[1] / "tools/hook-capture/claude-code"
DRIVER = CAPTURE / "drive-session-runs.py"
# The driver lives in the repo; don't leave a __pycache__ next to it.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("drive_session_runs", DRIVER)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

SINCE = 1_800_000_000_000


class PidTallyTests(unittest.TestCase):
    """S23 (#28): which hook events see a ppid other than their claude process?"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="claude-code capture ")
        self.addCleanup(self.temp.cleanup)
        self.events = Path(self.temp.name)
        self.n = 0

    def event(self, name, session, ppid, chain=(), at=SINCE + 1000):
        """One captured hook event as log.sh writes it: <name>.json and <name>.meta."""
        # This .meta follows log.sh's format; the log.sh test below checks that format.
        self.n += 1
        stem = f"{at // 1000}-{9000 + self.n}"
        (self.events / f"{stem}.meta").write_text(
            f"ts={at // 1000}\nppid={ppid}\nCLAUDE_PID=unset\n"
            "process chain (pid ppid comm):\n" + "".join(f"  {c}\n" for c in chain) +
            "env:\n  CLAUDE_PROJECT_DIR\nsession kind:\nterminal:\n")
        p = self.events / f"{stem}.json"
        p.write_text(json.dumps({"session_id": session, "hook_event_name": name}))
        os.utime(p, ns=(at * 1_000_000, at * 1_000_000))
        return f"{stem}.json"

    def tally(self, modes):
        return driver.pid_tally(str(self.events), SINCE, modes)

    def record(self, name, session, ppid, chain=()):
        """One event record as pid_counts takes it: (file, session_id, event, ppid, chain)."""
        self.n += 1
        return (f"{self.n}.json", session, name, ppid, list(chain))

    def test_an_event_log_sh_captured_counts_at_the_pid_that_ran_the_hook(self):
        # A copy, because log.sh writes next to itself: never into the repo's captures/.
        tool = tempfile.mkdtemp(prefix="claude-code log.sh ")
        self.addCleanup(shutil.rmtree, tool)
        shutil.copy(CAPTURE / "log.sh", tool)
        payload = {"session_id": "s-log", "hook_event_name": "SessionStart"}
        # Run without a shell in between, so log.sh's $PPID is this process.
        subprocess.run(["sh", os.path.join(tool, "log.sh")], input=json.dumps(payload),
                       text=True, check=True)
        events = os.path.join(tool, "captures", "events")
        [meta] = [n for n in os.listdir(events) if n.endswith(".meta")]
        ppid, chain = driver.read_meta(os.path.join(events, meta))
        self.assertEqual(ppid, os.getpid())
        if chain:  # empty where a sandbox blocks ps; the ppid line comes from $PPID alone
            self.assertEqual(chain[0].split()[0], str(os.getpid()))
        t = driver.pid_tally(events, 0, {os.getpid(): "interactive"})
        self.assertEqual(t["counts"], {"interactive": {
            "SessionStart": {"claude_pid": 1, "pid_1": 0, "other": 0, "missing": 0}}})
        self.assertEqual(t["outliers"], [])

    def test_events_at_their_claude_pid_count_as_such(self):
        self.event("SessionStart", "s-a", 101)
        self.event("SessionEnd", "s-a", 101)
        self.event("SessionEnd", "s-old", 1, at=SINCE - 1)  # before the run: ignored
        t = self.tally({101: "interactive"})
        self.assertEqual(t["counts"], {"interactive": {
            "SessionStart": {"claude_pid": 1, "pid_1": 0, "other": 0, "missing": 0},
            "SessionEnd": {"claude_pid": 1, "pid_1": 0, "other": 0, "missing": 0},
        }})
        self.assertEqual(t["outliers"], [])

    def test_late_hooks_with_pid_1_or_another_ppid_are_outliers_of_their_session(self):
        events = [self.record("SessionStart", "s-a", 101),
                  self.record("SessionEnd", "s-a", 1, ["4242 1 /bin/sh"]),
                  self.record("UserPromptSubmit", "s-b", 202),
                  self.record("Stop", "s-b", 777, ["777 202 node"])]
        late, stray = events[1][0], events[3][0]
        t = driver.pid_counts(events, {101: "interactive", 202: "headless"})
        self.assertEqual(t["repetitions"], {"headless": 1, "interactive": 1})
        self.assertEqual(t["counts"]["interactive"]["SessionEnd"],
                         {"claude_pid": 0, "pid_1": 1, "other": 0, "missing": 0})
        self.assertEqual(t["counts"]["headless"]["Stop"],
                         {"claude_pid": 0, "pid_1": 0, "other": 1, "missing": 0})
        self.assertEqual(t["outliers"], [
            {"file": late, "mode": "interactive", "event": "SessionEnd", "session_id": "s-a",
             "ppid": 1, "chain": ["4242 1 /bin/sh"]},
            {"file": stray, "mode": "headless", "event": "Stop", "session_id": "s-b",
             "ppid": 777, "chain": ["777 202 node"]},
        ])

    def test_a_repetition_without_the_event_counts_as_missing(self):
        events = [self.record("SessionStart", "s-a", 101),
                  self.record("SessionEnd", "s-a", 101),
                  self.record("SessionStart", "s-b", 102),
                  self.record("SessionStart", "s-c", 202)]
        t = driver.pid_counts(events, {101: "interactive", 102: "interactive", 202: "headless"})
        self.assertEqual(t["counts"]["interactive"]["SessionEnd"],
                         {"claude_pid": 1, "pid_1": 0, "other": 0, "missing": 1})
        self.assertEqual(t["counts"]["headless"]["SessionEnd"],
                         {"claude_pid": 0, "pid_1": 0, "other": 0, "missing": 1})

    def test_a_session_never_seen_at_a_started_pid_is_unknown(self):
        events = [self.record("SessionStart", "s-a", 101), self.record("SessionEnd", "s-x", 1)]
        orphan = events[1][0]
        t = driver.pid_counts(events, {101: "interactive"})
        self.assertEqual(t["counts"]["unknown"],
                         {"SessionEnd": {"claude_pid": 0, "pid_1": 1, "other": 0, "missing": 0}})
        self.assertEqual(t["counts"]["interactive"]["SessionEnd"],
                         {"claude_pid": 0, "pid_1": 0, "other": 0, "missing": 1})
        self.assertEqual([o["file"] for o in t["outliers"]], [orphan])


if __name__ == "__main__":
    unittest.main()
