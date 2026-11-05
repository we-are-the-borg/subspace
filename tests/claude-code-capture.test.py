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
from unittest import mock


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


WATCHER = CAPTURE / "watch-sessions.py"
spec = importlib.util.spec_from_file_location("watch_sessions", WATCHER)
watcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watcher)


# Built at runtime: tests/fixtures-privacy.test.py flags literal foreign home paths.
OTHER_HOME = "/Users/" + "someone"
USER_TEMP = "/var/folders/" + "ab/cdef123/T/"


class AttachHelperTests(unittest.TestCase):
    """S24 (#30): what the driver records about a `claude attach` client."""

    def test_the_job_id_is_the_first_line_claude_bg_prints(self):
        out = ("backgrounded · 35ad01b4\n  claude agents             list sessions\n"
               "  claude attach 35ad01b4    open in this terminal\n")
        self.assertEqual(driver.bg_job_id(out), "35ad01b4")
        self.assertIsNone(driver.bg_job_id("  claude attach 35ad01b4    open in this terminal\n"))
        self.assertIsNone(driver.bg_job_id(""))

    def test_status_files_of_a_session_are_picked_by_session_id_without_reading_keys(self):
        d = Path(tempfile.mkdtemp(prefix="claude-code sessions "))
        self.addCleanup(shutil.rmtree, d)
        (d / "101.json").write_text(json.dumps({"pid": 101, "sessionId": "s-job", "jobId": "j1"}))
        (d / "102.json").write_text(json.dumps({"pid": 102, "sessionId": "s-other"}))
        (d / "103.json").write_text("not json")
        # A key file that can't be opened: reading it would fail the test.
        key = d / "101.abc.key"
        key.write_text("secret")
        key.chmod(0)
        self.addCleanup(key.chmod, 0o600)
        self.assertEqual(driver.status_files_of(str(d), "s-job"),
                         [("101.json", {"pid": 101, "sessionId": "s-job", "jobId": "j1"})])
        self.assertEqual(driver.status_files_of(str(d / "missing"), "s-job"), [])

    def test_session_names_mask_the_hash_of_key_files(self):
        d = Path(tempfile.mkdtemp(prefix="claude-code sessions "))
        self.addCleanup(shutil.rmtree, d)
        for n in ("7.json", "7.0f3a9c.key", "12.json", ".12.json.tmp"):
            (d / n).write_text("{}")
        self.assertEqual(driver.session_names(str(d)),
                         [".12.json.tmp", "12.json", "7.*.key", "7.json"])
        self.assertEqual(driver.session_names(str(d / "missing")), [])

    def test_only_allowlisted_terminal_variables_leave_ps_e(self):
        out = (f"{OTHER_HOME}/.local/bin/claude attach 35ad01b4 HOME={OTHER_HOME} "
               "TERM_PROGRAM=WarpTerminal ANTHROPIC_API_KEY=sk-secret "
               "WARP_FOCUS_URL=warp://session/abc XTERM_PROGRAM=no TMUX_PANE=%3\n")
        self.assertEqual(driver.terminal_from_ps_env(out), {
            "TERM_PROGRAM": "WarpTerminal", "WARP_FOCUS_URL": "warp://session/abc",
            "TMUX_PANE": "%3"})
        self.assertEqual(driver.terminal_from_ps_env(""), {})

    def test_lsof_keeps_sockets_ttys_and_own_files_with_home_paths_anonymized(self):
        home = OTHER_HOME
        out = "\n".join([
            "p4242",
            "fcwd", "tDIR", f"n{home}/dev/x",
            "ftxt", "tREG", f"n{home}/.local/share/claude/versions/2.1.318",
            "ftxt", "tREG", "n/usr/lib/dyld",
            "ftxt", "tREG", "n/System/Library/x.dylib",
            "f0", "tCHR", "n/dev/ttys012",
            "f3", "tKQUEUE", "ncount=0, state=0x8",
            "f4", "tPIPE", "n->0x1234",
            "f5", "tunix", "n/tmp/cc-daemon-501/abc/pty/35ad01b4.sock",
            "f6", "tIPv4", "n10.0.0.2:5555->1.2.3.4:443",
            "f7", "tREG", "n/private/tmp/claude-501/-Users-" + "someone-dev-x/t.out",
            "f8", "tREG", f"n/private{USER_TEMP}x.tmp",
            "f9", "tunix", "n->0xabc",
        ]) + "\n"
        self.assertEqual(driver.lsof_open(out, home), [
            {"fd": "cwd", "type": "DIR", "name": "/Users/user/dev/x"},
            {"fd": "txt", "type": "REG",
             "name": "/Users/user/.local/share/claude/versions/2.1.318"},
            {"fd": "0", "type": "CHR", "name": "/dev/ttys012"},
            {"fd": "5", "type": "unix", "name": "/tmp/cc-daemon-501/abc/pty/35ad01b4.sock"},
            {"fd": "6", "type": "IPv4"},
            {"fd": "7", "type": "REG", "name": "/private/tmp/claude-501/-Users-user-dev-x/t.out"},
            {"fd": "8", "type": "REG", "name": "/private/var/folders/<user temp>/T/x.tmp"},
            {"fd": "9", "type": "unix", "name": "->0xabc"},
        ])

    def test_key_paths_name_structure_never_values(self):
        doc = {"pid": 1, "ptyAuth": "secret", "dispatch": {"env": {"A": "x"}, "args": ["a", "b"]},
               "none": None, "empty": []}
        self.assertEqual(driver.key_paths(doc), [
            "/dispatch/args[]: str", "/dispatch/env/A: str", "/empty[]", "/none: null",
            "/pid: int", "/ptyAuth: str"])

    def test_process_chain_and_children_from_ps(self):
        ps = ("    1     0 /sbin/launchd\n"
              "  500     1 /Applications/Warp.app/Contents/MacOS/stable\n"
              "  600   500 /bin/zsh\n"
              f"  700   600 {OTHER_HOME}/.local/share/claude/versions/2.1.318\n"
              "  701   700 /bin/sh\n")
        rows = driver.ps_table(ps)
        self.assertEqual(driver.process_chain(rows, 700),
                         ["700 600 2.1.318", "600 500 zsh", "500 1 stable", "1 0 launchd"])
        self.assertEqual(driver.process_chain(rows, 999), [])
        self.assertEqual(driver.children(rows, 700), ["701 700 sh"])

    def test_cleanup_jobs_are_logged_under_the_run_that_asked(self):
        agents = json.dumps([
            {"id": "a7741313", "cwd": driver.HERE, "startedAt": SINCE + 1},
            {"id": "older", "cwd": driver.HERE, "startedAt": SINCE - 1},
            {"id": "elsewhere", "cwd": "/", "startedAt": SINCE + 1}])
        logged = []
        with mock.patch.object(driver.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, agents, "")), \
                mock.patch.object(driver, "action",
                                  lambda run, what, **extra: logged.append((run, what))):
            self.assertEqual(driver.s22_jobs(SINCE, "S24"), ["a7741313"])
            self.assertEqual(driver.s22_jobs(SINCE), ["a7741313"])
        self.assertEqual(logged, [("S24", "jobs found for cleanup"),
                                  ("S22", "jobs found for cleanup")])


class WatcherTests(unittest.TestCase):
    """Which status files watch-sessions.py records: never the user's other sessions."""

    def test_files_in_the_capture_dir_or_of_a_recorded_session_are_wanted(self):
        here = watcher.HERE
        self.assertTrue(watcher.wanted({"cwd": here, "sessionId": "a"}, set()))
        self.assertTrue(watcher.wanted({"cwd": os.path.join(here, "sub"), "sessionId": "a"}, set()))
        self.assertTrue(watcher.wanted({"cwd": "/elsewhere", "sessionId": "job"}, {"job"}))
        self.assertFalse(watcher.wanted({"cwd": "/elsewhere", "sessionId": "other"}, {"job"}))
        self.assertFalse(watcher.wanted({"cwd": here + "-sibling", "sessionId": "x"}, set()))
        self.assertFalse(watcher.wanted({"cwd": "/elsewhere"}, {None}))
        self.assertFalse(watcher.wanted(None, set()))

    def test_other_files_leave_only_their_kind_and_status(self):
        doc = {"pid": 9, "sessionId": "s", "cwd": OTHER_HOME, "name": "secret project",
               "kind": "bg", "spare": True, "status": "idle", "jobId": "abcd1234"}
        self.assertEqual(watcher.summary(doc), {"kind": "bg", "spare": True, "status": "idle"})
        self.assertEqual(watcher.summary({"kind": "interactive"}), {"kind": "interactive"})
        self.assertEqual(watcher.summary("not a dict"), {})

    def test_a_new_foreign_file_is_logged_untracked_once_and_never_if_present_at_start(self):
        foreign = {"cwd": "/elsewhere", "sessionId": "other", "kind": "bg"}
        self.assertEqual(watcher.action("1.json", None, foreign, set(), set(), set()), "untracked")
        self.assertIsNone(watcher.action("1.json", None, foreign, set(), {"1.json"}, set()))
        self.assertIsNone(watcher.action("1.json", None, foreign, set(), set(), {"1.json"}))
        # Caught mid-write: neither logged nor recorded, the next scan reads it whole.
        self.assertIsNone(watcher.action("1.json", None, None, set(), set(), set()))

    def test_a_wanted_or_already_recorded_file_is_recorded_even_if_quiet_or_untracked(self):
        mine = {"cwd": watcher.HERE, "sessionId": "a"}
        self.assertEqual(watcher.action("1.json", None, mine, set(), {"1.json"}, {"1.json"}), "record")
        job = {"cwd": "/elsewhere", "sessionId": "job"}
        self.assertEqual(watcher.action("1.json", None, job, {"job"}, set(), {"1.json"}), "record")
        # Once a pid is recorded it stays recorded, whatever its file says now.
        old = (1, 2, 3, b"{}")
        self.assertEqual(watcher.action("1.json", old, {"cwd": "/elsewhere"}, set(), set(), set()), "record")


if __name__ == "__main__":
    unittest.main()
