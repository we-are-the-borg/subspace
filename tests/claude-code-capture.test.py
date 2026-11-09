"""Synthetic checks of the Claude Code capture driver; never starts Claude Code."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
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


def effort_dialog(level):
    """The typed command, then the 2.1.319 confirm dialog (texts from the binary)."""
    return ("❯/effort" + level + "Changeeffortlevel?Yournextresponsewillbeslowerandusemore"
            "tokensThisconversationiscachedforthecurrenteffortlevel.Switchingto" + level +
            "meansthefullhistorygetsre-read.❯1.Yes,switchto" + level + "2.No,goback").encode()


class EffortReplyTests(unittest.TestCase):
    """S25 (#37): what the TUI answered to `/effort <level>`, read off the screen."""

    # Session.out drops ANSI codes and whitespace; the texts are 2.1.319's.
    MENU = "❯/effortlow/effortSeteffortlevelformodelusage".encode()
    LINE = "────".encode()

    def reply(self, level, text):
        """The command as the transcript shows it, its answer after ⎿, the prompt box."""
        return f"/effort{level}⎿{text}".encode() + self.LINE + "❯".encode()

    def test_nothing_but_the_typed_command_and_its_menu_is_no_reply(self):
        self.assertEqual(driver.effort_reply(self.MENU, "low"), (None, b""))
        self.assertEqual(driver.effort_reply(b"", "low"), (None, b""))

    def test_a_set_level_is_read_up_to_the_prompt_box(self):
        text = "Seteffortleveltolow(savedasyourdefaultfornewsessions):Quick○low·/effort"
        self.assertEqual(driver.effort_reply(self.MENU + self.reply("low", text), "low"),
                         ("set", text.encode()))

    def test_an_answer_to_an_earlier_command_still_on_screen_is_no_reply(self):
        # Re-drawn after the driver cleared its buffer, before the new answer came.
        stale = self.reply("low", "Seteffortleveltolow(saved)") + b"/effortauto"
        self.assertEqual(driver.effort_reply(stale, "auto"), (None, b""))

    def test_each_answer_has_its_kind_also_when_drawn_over_an_older_one(self):
        # The TUI redraws only changed cells: "Effort level set to auto" over
        # "Set effort level to low" leaves "Effortlevelettoauto" in the stream.
        for level, text, kind in (
                ("max", "Effort'max'exceedsthecapforsonnet;setto'high'instead", "capped"),
                ("auto", "Effortlevelsettoauto◐medium·/effort", "auto"),
                ("auto", "Effortlevelettoauto◐medium·/effort", "auto"),
                ("high", "Failedtoseteffortlevel:boom", "failed"),
                ("high", "Notapplied:CLAUDE_CODE_EFFORT_LEVEL=lowoverrideseffort", "not applied"),
                ("high", "Kepteffortlevelaslow", "kept"),
                ("high", "Somethingnew", "unknown")):
            with self.subTest(text=text):
                self.assertEqual(driver.effort_reply(self.reply(level, text), level)[0], kind)

    def test_the_confirm_dialog_counts_until_an_answer_follows_it(self):
        dialog = "Changeeffortlevel?Yournextresponsewillbeslower❯1.Yes2.No,goback".encode()
        self.assertEqual(driver.effort_reply(self.MENU + dialog, "high")[0], "dialog")
        self.assertEqual(driver.effort_reply(
            self.MENU + dialog + self.reply("high", "Seteffortleveltohigh(saved)"), "high")[0],
            "set")

    def test_after_the_confirm_dialog_the_next_answer_counts_without_the_command_redrawn(self):
        self.assertEqual(driver.effort_reply(self.MENU + effort_dialog("auto"), "auto")[0], "dialog")
        answer = "⎿Effortlevelsettoauto◐medium·/effort".encode()
        self.assertEqual(driver.effort_reply(
            self.MENU + effort_dialog("auto") + answer + self.LINE + "❯".encode(), "auto"),
            ("auto", answer[len("⎿".encode()):]))


class FakeTui:
    """The pseudo-terminal as set_effort sees it: what each read adds, on a fake clock."""

    def __init__(self, reads):
        self.reads, self.out, self.clock, self.typed = reads, b"", 0.0, []

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += seconds
        while self.reads and self.reads[0][0] <= self.clock:
            self.out += self.reads.pop(0)[1]

    def clear(self):
        self.out = b""

    def send(self, text):
        self.typed.append(text)

    def keys(self, what, keys):
        self.typed.append(keys)
        # The answer comes only after the confirm, and later than 20 s after the send.
        self.reads.append((self.clock + 19.5, self.answer))


class SetEffortTests(unittest.TestCase):
    """S25: `/effort <level>` through the confirm dialog, answer read in a later read."""

    def test_a_confirmed_dialog_keeps_the_answer_that_follows_and_waits_for_it_anew(self):
        dialog = effort_dialog("max")
        tui = FakeTui([(1, dialog)])
        tui.answer = "⎿Seteffortleveltomax(thissessiononly):Maximum◈max·/effort────❯".encode()
        logged = []
        with mock.patch.object(driver, "action",
                               lambda run, what, **extra: logged.append((what, extra))):
            kind = driver.set_effort(tui, "max", "S25", now=tui.now, sleep=tui.sleep)
        self.assertEqual(kind, "set")
        self.assertEqual(tui.typed, ["/effort max", "\r"])
        self.assertEqual(logged, [("effort answer", {
            "level": "max", "kind": "set", "dialog": True,
            "screen": "Seteffortleveltomax(thissessiononly):Maximum◈max·/effort"})])

    def test_no_answer_after_the_confirm_times_out_from_the_confirm(self):
        tui = FakeTui([(1, effort_dialog("max"))])
        tui.answer = b""
        with mock.patch.object(driver, "action", lambda *a, **k: None), \
                self.assertRaises(TimeoutError):
            driver.set_effort(tui, "max", "S25", now=tui.now, sleep=tui.sleep)
        self.assertGreater(tui.clock, 1 + 20)  # the confirm restarted the 20 s


class EffortRestoreTests(unittest.TestCase):
    """S25 ends with the sonnet effort level the user had saved before it started."""

    def test_a_saved_level_is_set_again_and_none_saved_means_auto(self):
        self.assertEqual(driver.restore_level({"effortLevel": "high"}), "high")
        self.assertEqual(driver.restore_level({}), "auto")  # what `/effort auto` leaves
        self.assertEqual(driver.restore_level(None), "auto")

    def test_only_the_sonnet_entry_of_model_settings_is_read(self):
        settings = {"theme": "dark", "modelSettings": {
            "claude-opus-5-5": {"effortLevel": "high"}, "claude-sonnet-5-5": {"effortLevel": "low"}}}
        self.assertEqual(driver.sonnet_model_settings(settings), {"effortLevel": "low"})
        self.assertIsNone(driver.sonnet_model_settings({"modelSettings": {"claude-opus-5-5": {}}}))
        self.assertIsNone(driver.sonnet_model_settings(None))


class TypingGuardTests(unittest.TestCase):
    """S25: typing into the TUI only where the screen shows its idle prompt."""

    # What Session.out had since the TUI was last idle (2.1.316/2.1.319 texts).
    IDLE = "❯/effortxhigh⎿Seteffortleveltoxhigh(saved)◉xhigh·/effort────❯────".encode()
    PERMISSION = ("❯Runexactlythis⏺Bash(touchx)Doyouwanttoproceed?❯1.Yes2.Yes,andalwaysallow"
                  "3.NoEsctocancel·Tabtoamend✽Nebulizing…(2s·↓251tokens)").encode()

    def test_an_idle_prompt_or_nothing_drawn_lets_the_driver_type(self):
        self.assertIsNone(driver.typing_blocker(self.IDLE))
        self.assertIsNone(driver.typing_blocker(b""))
        # A collapsed tool output is no spinner.
        self.assertIsNone(driver.typing_blocker(self.IDLE + "⎿a…(+3morelines)".encode()))

    def test_a_dialog_on_screen_blocks_typing(self):
        for screen in (self.PERMISSION,
                       "Changeeffortlevel?Yournextresponsewillbeslower❯1.Yes,switchtomax".encode(),
                       b"AllowexternalCLAUDE.mdfileimports?Entertoconfirm",
                       b"Backgroundworkisrunning"):
            with self.subTest(screen=screen):
                self.assertEqual(driver.typing_blocker(self.IDLE + screen), "dialog open")

    def test_a_turn_still_running_blocks_typing(self):
        for screen in ("✢Seasoning…(runningUserPromptSubmithooks…2/5·0s)".encode(),
                       "✽Roosting…(0s·↓34tokens)".encode(),
                       "✻Waitingfor1backgroundagenttofinish".encode()):
            with self.subTest(screen=screen):
                self.assertEqual(driver.typing_blocker(self.IDLE + screen), "turn running")

    def test_waiting_for_several_background_agents_blocks_typing(self):
        # S25's tty log (2.1.319) after the Agent calls, as the pty wrote it: no "(digit" spinner.
        raw = (b"\x1b[38;2;147;154;183m\xe2\x9c\xbb\x1b[3GWaiting for \x1b[1m2\x1b[22m background "
               b"agents to finish\r\x1b[1B\x1b[39m\x1b[K\r\x1b[1B\x1b[38;2;245;169;127m\xe2\x9c\xbb"
               b"\x1b[3GBefuddling\xe2\x80\xa6 \r\x1b[1B\x1b[39m\x1b[K")
        self.assertEqual(driver.typing_blocker(self.IDLE + driver.ANSI.sub(b"", raw)),
                         "turn running")


class ScreenPositionTests(unittest.TestCase):
    """Session.out keeps the last 20000 bytes; a position taken in it survives that trim."""

    def session(self):
        s = driver.Session.__new__(driver.Session)  # no pty: only the screen buffer
        s.out, s.total, s.lock = b"", 0, threading.RLock()
        return s

    def test_what_was_drawn_after_a_position_is_kept_also_when_the_buffer_was_trimmed(self):
        s = self.session()
        s.add(b"a" * 19990)
        pos = s.total
        s.add(b"b" * 20)
        self.assertEqual(len(s.out), 20000)  # 10 bytes of "a" trimmed away
        self.assertEqual(s.since(pos), b"b" * 20)

    def test_a_position_already_trimmed_away_keeps_the_whole_buffer(self):
        s = self.session()
        s.add(b"a" * 100)
        pos = s.total
        s.add(b"b" * 20000 + b"c")
        self.assertEqual(s.since(pos), b"b" * 19999 + b"c")

    def test_text_dropped_from_the_buffer_never_costs_what_was_drawn_after_a_position(self):
        s = self.session()
        s.add(b"titlerest")
        s.out = s.out.replace(b"title", b"")  # as ready() drops an answered dialog's title
        pos = s.total
        s.add(b"after")
        self.assertEqual(s.since(pos), b"after")
        s.out = s.out.replace(b"t", b"")  # dropped after the position: keeps more, never less
        self.assertEqual(s.since(pos), b"safer")  # all of "afer", one byte more


class WatchedLock:
    """Session's lock; sets `contended` when another thread has to wait for it."""

    def __init__(self, contended):
        self.lock, self.contended = threading.RLock(), contended

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


class RacingSession(driver.Session):
    """Session's screen buffer (no pty) with the drain thread's add() run at a chosen moment.

    race("total", text): add(text) runs right after the main thread reads total;
    race("out", text): right before it stores out. The main thread goes on once
    that add() is done or waits for the lock.
    """

    def __init__(self):
        self.moved = threading.Event()
        self.lock, self._out, self._total = WatchedLock(self.moved), b"", 0
        self.at = self.drawn = None
        self.drains = []

    def race(self, at, text):
        self.at, self.drawn = at, text

    def join(self):
        for t in self.drains:
            t.join(5)

    def _hook(self, at):
        if self.at != at:
            return
        self.at, text = None, self.drawn

        def drain():
            self.add(text)
            self.moved.set()

        t = threading.Thread(target=drain)
        self.drains.append(t)
        t.start()
        self.moved.wait(5)

    @property
    def total(self):
        value = self._total
        self._hook("total")
        return value

    @total.setter
    def total(self, value):
        self._total = value

    @property
    def out(self):
        return self._out

    @out.setter
    def out(self, value):
        self._hook("out")
        self._out = value


class ScreenRaceTests(unittest.TestCase):
    """The drain thread adds to Session.out while the main thread reads and rewrites it."""

    def test_what_was_drawn_after_a_position_is_read_whole_while_the_drain_thread_adds(self):
        s = RacingSession()
        s.add(b"screen:")
        pos = s.total
        s.add("Doyouwanttoproceed?".encode())
        s.race("total", "❯1.Yes".encode())
        seen = s.since(pos)
        s.join()
        self.assertIn(seen, ("Doyouwanttoproceed?".encode(), "Doyouwanttoproceed?❯1.Yes".encode()))
        self.assertEqual(s.since(pos), "Doyouwanttoproceed?❯1.Yes".encode())

    def test_rewriting_the_buffer_never_loses_what_the_drain_thread_adds_meanwhile(self):
        cuts = (("keep_since", lambda s, pos: s.keep_since(pos), b"restafter"),
                ("keep_from", lambda s, pos: s.keep_from(lambda out: out.find(b"st")), b"stafter"),
                ("drop", lambda s, pos: s.drop(b"title"), b"restafter"),
                ("clear", lambda s, pos: s.clear(), b"after"))
        for name, cut, kept in cuts:
            with self.subTest(name):
                s = RacingSession()
                s.add(b"title")
                pos = s.total
                s.add(b"rest")
                s.race("out", b"after")
                cut(s, pos)
                s.join()
                self.assertEqual(s.out, kept)

    def test_a_cut_at_no_mark_keeps_the_whole_buffer(self):
        s = RacingSession()
        s.add(b"titlerest")
        s.keep_from(lambda out: out.find(b"missing"))
        self.assertEqual(s.out, b"titlerest")


class FakeS25:
    """S25's pseudo-terminal, hook events and clock as s25() sees them; never starts Claude Code.

    Each prompt draws its spinner and fires UserPromptSubmit, then Stop; what the
    TUI draws after a Stop shows up on the next sleep. `hang` maps a prompt to the
    screen it stays at, without a Stop; `late` maps a prompt to what is drawn
    after its Stop; `lost` are prompts the TUI never submits (no event, no
    spinner); `dialogs` are the levels whose `/effort` asks to confirm. SessionStart
    (with `model`) fires at once, or after the Enter on a known startup dialog,
    which the real Session.ready() answers; `after_startup` is drawn after that
    Enter, on the next sleep, `at_enter` at once, while keys() still runs (the
    drain thread racing ready()). Texts are 2.1.316/2.1.319's as Session.out has them;
    everything drawn goes through Session.add, so the buffer keeps its last 20000 bytes.
    """

    SPINNER = "✽Roosting…(0s·↓34tokens)".encode()
    WAITING = "✻Waitingfor2backgroundagentstofinish✻Befuddling…".encode()
    IDLE = "✻Cookedfor2s·done❯".encode()

    def __init__(self, startup=b"", hang=None, late=None, dialogs=(), lost=(),
                 model=driver.SONNET, after_startup=b"", at_enter=b""):
        self.out, self.total, self.lock = b"", 0, threading.RLock()
        self.add(startup)
        self.hang, self.late, self.dialogs = hang or {}, late or {}, dialogs
        self.after_startup, self.at_enter = after_startup, at_enter
        self.lost, self.model, self.started = lost, model, 0
        self.typed, self.events, self.pending, self.clock = [], [], b"", 0.0
        self.startup_dialog = any(d in startup for d in driver.DIALOGS)
        if not self.startup_dialog:
            self.fire("SessionStart", model=model)

    # Session
    def __call__(self, run, args=(), model=None, env=None):
        driver.LIVE.append(self)
        return self

    ready, add, since = driver.Session.ready, driver.Session.add, driver.Session.since
    keep_since, keep_from, drop, clear = (driver.Session.keep_since, driver.Session.keep_from,
                                          driver.Session.drop, driver.Session.clear)

    def send(self, text):
        self.typed.append(text)
        if text in self.lost:
            self.add(f"❯{text}".encode())
            return self.clock
        if text.startswith("/effort "):
            level = text.split()[1]
            if level in self.dialogs:
                self.add(effort_dialog(level))
            else:
                self.add(f"❯/effort{level}".encode() + self.answer(level))
            return self.clock
        n = f"prompt-{len(self.typed)}"
        self.add(f"❯{text}".encode() + self.SPINNER)
        self.fire("UserPromptSubmit", prompt=text, prompt_id=n)
        if text in self.hang:
            self.add(self.hang[text])
        elif "Agent tool" in text:
            self.add(self.WAITING)
            for agent in ("agent-1", "agent-2"):
                self.fire("SubagentStop", agent_type="general-purpose", agent_id=agent)
            for agent in ("agent-1", "agent-2"):
                self.fire("UserPromptSubmit", prompt=f"<task-notification>{agent}",
                          prompt_id=f"{n}-{agent}")
                self.fire("Stop", prompt_id=f"{n}-{agent}")
        else:
            self.fire("Stop", prompt_id=n, late=self.late.get(text, b""))
        return self.clock

    def keys(self, what, keys):
        self.typed.append(keys)
        if self.startup_dialog:  # the startup dialog's Enter lets the session start
            self.startup_dialog = False
            self.fire("SessionStart", model=self.model)
            self.add(self.at_enter)
            self.pending += self.after_startup
            return
        level = self.out.rsplit(b"switchto", 1)[1].split(b"2.", 1)[0].decode()
        self.add(self.answer(level))  # the confirm draws the answer

    def answer(self, level):
        text = "Effortlevelsettoauto◐medium·/effort" if level == "auto" else \
            f"Seteffortlevelto{level}(savedasyourdefaultfornewsessions)"
        return f"⎿{text}────❯".encode()

    def fire(self, name, **fields):
        self.events.append({"hook_event_name": name, **fields})

    def wait(self, name, since, timeout=90, pred=None):
        for ev in self.events:
            if ev["hook_event_name"] == name and (pred is None or pred(ev)):
                if name == "Stop":
                    self.pending += ev.get("late", b"") + self.IDLE
                return ev
        self.clock += timeout
        raise TimeoutError(f"no {name} within {timeout}s")

    def exit(self):
        self.typed.append("/exit")
        driver.LIVE.remove(self)

    # time
    def time(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += seconds
        self.add(self.pending)
        self.pending = b""


class S25RunTests(unittest.TestCase):
    """S25 as a whole: nothing typed into a dialog or a running turn, the saved level put back."""

    PERMISSION = TypingGuardTests.PERMISSION
    AT_HIGH = "Run exactly this Bash command once and nothing else: echo high"

    def run_s25(self, tui):
        config = tempfile.mkdtemp(prefix="claude-code config ")
        self.addCleanup(shutil.rmtree, config)
        # No sonnet entry saved: S25 puts that back with `/effort auto`.
        Path(config, "settings.json").write_text(json.dumps({"theme": "dark"}))
        self.addCleanup(lambda: tui in driver.LIVE and driver.LIVE.remove(tui))
        self.logged = []
        with mock.patch.object(driver, "Session", tui), mock.patch.object(driver, "time", tui), \
                mock.patch.object(driver, "CONFIG", config), \
                mock.patch.object(driver, "action",
                                  lambda run, what, **extra: self.logged.append((what, extra))):
            driver.s25()

    def logged_restore(self):
        return [(w, e) for w, e in self.logged if w.startswith("effort restore")]

    def test_an_idle_end_puts_the_saved_level_back_before_exiting(self):
        tui = FakeS25(dialogs=("max",))
        self.run_s25(tui)
        self.assertEqual(tui.typed[-2:], ["/effort auto", "/exit"])
        self.assertEqual(tui.typed[tui.typed.index("/effort max") + 1], "\r")  # confirmed
        self.assertEqual(self.logged_restore(), [])

    def test_a_turn_stuck_at_a_dialog_or_still_running_gets_no_keystroke_after_the_timeout(self):
        for screen, reason in ((self.PERMISSION, "dialog open"), (b"", "turn running")):
            with self.subTest(reason=reason):
                tui = FakeS25(hang={self.AT_HIGH: screen})
                with self.assertRaises(TimeoutError):
                    self.run_s25(tui)
                self.assertEqual(tui.typed[-1], self.AT_HIGH)
                self.assertEqual(self.logged_restore(), [
                    ("effort restore skipped", {"level": "auto", "reason": reason})])

    def test_a_dialog_ready_does_not_know_stops_the_run_before_the_first_keystroke(self):
        tui = FakeS25(startup="Doyouwanttoproceed?❯1.Yes2.No".encode())
        with self.assertRaisesRegex(RuntimeError, "first prompt: dialog open"):
            self.run_s25(tui)
        self.assertEqual(tui.typed, [])
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "dialog open"})])

    def test_a_known_startup_dialog_is_answered_and_its_leftovers_dont_stop_the_first_prompt(self):
        # ready() drops only the title; the rest of the dialog stays in Session.out (synthetic).
        dialog = "AllowexternalCLAUDE.mdfileimports?❯1.Yes,allow2.NoEntertoconfirm·Esctocancel"
        tui = FakeS25(startup=dialog.encode())
        self.run_s25(tui)
        self.assertEqual(tui.typed[:2], ["\r", "Run exactly this Bash command once and nothing else: "
                                         "echo default"])
        self.assertEqual(tui.typed[-2:], ["/effort auto", "/exit"])
        self.assertEqual(self.logged_restore(), [])

    def test_a_dialog_drawn_after_the_known_startup_dialog_stops_the_run_before_the_first_prompt(self):
        dialog = "AllowexternalCLAUDE.mdfileimports?❯1.Yes,allow2.NoEntertoconfirm·Esctocancel"
        tui = FakeS25(startup=dialog.encode(), after_startup="Doyouwanttoproceed?❯1.Yes2.No".encode())
        with self.assertRaisesRegex(RuntimeError, "first prompt: dialog open"):
            self.run_s25(tui)
        self.assertEqual(tui.typed, ["\r"])  # only ready()'s Enter on the known dialog
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "dialog open"})])

    def test_a_dialog_drawn_after_the_known_startup_dialog_stops_the_run_also_past_the_trim(self):
        # The buffer is full at the Enter, and more than it holds is drawn after it (synthetic).
        dialog = "AllowexternalCLAUDE.mdfileimports?❯1.Yes,allow2.NoEntertoconfirm·Esctocancel"
        banner = "─" * 7000  # 21000 bytes
        unknown = "Doyouwanttoproceed?❯1.Yes2.Yes,andalwaysallowfromthisproject3.No"
        tui = FakeS25(startup=(banner + dialog).encode(), after_startup=(banner + unknown).encode())
        with self.assertRaisesRegex(RuntimeError, "first prompt: dialog open"):
            self.run_s25(tui)
        self.assertEqual(tui.typed, ["\r"])  # only ready()'s Enter on the known dialog
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "dialog open"})])

    def test_a_dialog_drawn_while_the_enter_on_the_known_startup_dialog_is_typed_stops_the_run(self):
        # The drain thread adds what the TUI draws right after the Enter, before keys() returns.
        dialog = "AllowexternalCLAUDE.mdfileimports?❯1.Yes,allow2.NoEntertoconfirm·Esctocancel"
        tui = FakeS25(startup=dialog.encode(), at_enter="Doyouwanttoproceed?❯1.Yes2.No".encode())
        with self.assertRaisesRegex(RuntimeError, "first prompt: dialog open"):
            self.run_s25(tui)
        self.assertEqual(tui.typed, ["\r"])  # only ready()'s Enter on the known dialog
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "dialog open"})])

    def test_another_model_than_sonnet_stops_the_run_before_anything_is_typed(self):
        tui = FakeS25(model="claude-sonnet-6-0")
        with self.assertRaisesRegex(RuntimeError, "claude-sonnet-6-0"):
            self.run_s25(tui)
        self.assertEqual(tui.typed, [])
        self.assertIn(("unexpected model", {"model": "claude-sonnet-6-0", "expected": driver.SONNET}),
                      self.logged)
        self.assertEqual(self.logged_restore(), [])

    def test_a_prompt_never_submitted_gets_no_restore_typed_into_its_box(self):
        tui = FakeS25(lost=(self.AT_HIGH,))
        with self.assertRaises(TimeoutError):
            self.run_s25(tui)
        self.assertEqual(tui.typed[-1], self.AT_HIGH)
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "prompt not confirmed"})])

    def test_a_dialog_drawn_after_a_stop_stops_the_run_before_the_next_keystroke(self):
        tui = FakeS25(late={self.AT_HIGH: self.PERMISSION})
        with self.assertRaisesRegex(RuntimeError, "dialog open"):
            self.run_s25(tui)
        self.assertEqual(tui.typed[-1], self.AT_HIGH)
        self.assertEqual(self.logged_restore(), [
            ("effort restore skipped", {"level": "auto", "reason": "dialog open"})])


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
