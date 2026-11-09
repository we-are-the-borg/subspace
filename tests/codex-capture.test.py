"""Synthetic capture-tool checks; never starts Codex or reads real rollouts."""
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tools/hook-capture/codex"
SHELL = os.environ.get("CAPTURE_SH", "sh")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex capture ")
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        for name in ("log.sh", "collect.sh"):
            shutil.copyfile(SOURCE / name, self.here / name)
        self.events = self.here / "captures/events"

    def log(self, payload, **kwargs):
        return subprocess.run(
            [SHELL, str(self.here / "log.sh")], input=payload,
            capture_output=True, check=True, timeout=1, **kwargs,
        )

    def test_subscription(self):
        config = json.loads((SOURCE / ".codex/hooks.json").read_text())
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), {
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
            "SubagentStart", "SubagentStop", "Stop", "Interrupt",
        })
        for groups in config["hooks"].values():
            self.assertEqual(groups, [{"hooks": [{
                "type": "command", "command": "sh ./log.sh", "async": True,
            }]}])

    def test_raw_bytes_metadata_and_deadline(self):
        payload = b' {\r\n "hook_event_name": "Interrupt", "text": "\\n\\\\"\r\n}\n\n'
        env = dict(os.environ, CODEX_CAPTURE_TEST="secret-a",
                   PLUGIN_CAPTURE_TEST="secret-b", CLAUDE_CAPTURE_TEST="secret-c",
                   SHELL="/example/shell")
        started = time.monotonic()
        result = self.log(payload, env=env)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual((result.stdout, result.stderr), (b"", b""))
        files = list(self.events.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), payload)
        meta = files[0].with_suffix(".meta").read_text()
        self.assertIn(f"ppid={os.getpid()}\n", meta)
        self.assertIn("SHELL=/example/shell\n", meta)
        self.assertIn(f"argv0={self.here / 'log.sh'}\n", meta)
        for prefix in ("CODEX", "PLUGIN", "CLAUDE"):
            self.assertIn(f"  {prefix}_CAPTURE_TEST\n", meta)
        self.assertNotIn("secret-", meta)
        # Verify every ancestor from this test process through PID 1, including
        # its full ps row (comm and args), against a separate process snapshot.
        snapshot = subprocess.check_output(
            ["ps", "-ww", "-eo", "pid=,ppid=,comm=,args="], text=True,
        )
        rows = {int(row.split()[0]): row for row in snapshot.splitlines()}
        pid = os.getpid()
        while True:
            self.assertIn("  " + rows[pid] + "\n", meta)
            if pid == 1:
                break
            pid = int(rows[pid].split()[1])
        self.assertEqual(list(self.events.glob(".*")), [])

    def test_concurrent_writes(self):
        payload = '{"hook_event_name":"Stop","text":"日本 🚀"}\n'.encode()
        processes = [subprocess.Popen(
            [SHELL, str(self.here / "log.sh")], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(12)]
        for process in processes:
            self.assertEqual(process.communicate(payload, timeout=5), (b"", b""))
            self.assertEqual(process.returncode, 0)
        files = list(self.events.glob("*.json"))
        self.assertEqual(len(files), 12)
        for file in files:
            self.assertEqual(file.read_bytes(), payload)
            self.assertTrue(file.with_suffix(".meta").is_file())
        self.assertEqual(list(self.events.glob(".*")), [])

    def test_unwritable_capture_is_silent(self):
        (self.here / "captures").write_text("directory blocked")
        result = self.log(b'{"hook_event_name":"Stop"}')
        self.assertEqual((result.stdout, result.stderr), (b"", b""))

    def test_collection_parent_child_spaces_and_missing(self):
        self.events.mkdir(parents=True)
        paths = []
        for directory, content in (("parent", b"parent bytes\r\n"),
                                   ('child "quoted"', b"child bytes\n")):
            path = self.here / directory / "rollout.jsonl"
            path.parent.mkdir()
            path.write_bytes(content)
            paths.append(path)
        (self.events / "pretty.json").write_text(json.dumps({
            "transcript_path": str(paths[0]), "agent_transcript_path": str(paths[1]),
        }, indent=2))
        (self.events / "nullable.json").write_text('{"transcript_path":null}')
        command = [SHELL, str(self.here / "collect.sh")]
        subprocess.run(command, check=True, capture_output=True)
        copies = list((self.here / "captures/transcripts").glob("*/rollout.jsonl"))
        self.assertEqual(len(copies), 2)
        self.assertEqual({p.read_bytes() for p in copies}, {p.read_bytes() for p in paths})
        for copy in copies:
            original = Path((copy.parent / "source.txt").read_text().strip())
            self.assertEqual(copy.read_bytes(), original.read_bytes())
        # Re-collection updates a rollout that was still being flushed.
        paths[0].write_bytes(b"updated parent\n")
        subprocess.run(command, check=True, capture_output=True)
        self.assertIn(b"updated parent\n", {p.read_bytes() for p in copies})
        (self.events / "missing.json").write_text(json.dumps({
            "transcript_path": str(self.here / "missing.jsonl"),
        }))
        (self.events / "invalid.json").write_text("invalid JSON")
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"missing rollout:", result.stderr)
        self.assertIn(b"cannot read invalid.json:", result.stderr)


def load_driver():
    spec = importlib.util.spec_from_file_location(
        "drive_review_runs", SOURCE / "drive-review-runs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DriverScreenTests(unittest.TestCase):
    """The driver reads the rendered screen before every keystroke."""

    def setUp(self):
        self.driver = load_driver()

    def render(self, data, rows=6, cols=30):
        screen = self.driver.Screen(rows, cols)
        screen.feed(data)
        return screen.lines()

    def test_screen_places_text_at_cursor_positions(self):
        lines = self.render(b"\x1b[2;3Hhello\x1b[1;1H\x1b[1mtop\x1b[0m")
        self.assertEqual(lines[0], "top")
        self.assertEqual(lines[1], "  hello")

    def test_screen_erases_line_and_display_from_cursor(self):
        lines = self.render(b"\x1b[1;1Hkeep this\x1b[2;1Hold row\x1b[3;1Hgone"
                            b"\x1b[1;5H\x1b[K\x1b[2;4H\x1b[J")
        self.assertEqual(lines[:3], ["keep", "old", ""])

    def test_screen_refuses_erase_modes_it_does_not_model(self):
        for sequence in (b"\x1b[1K", b"\x1b[2K", b"\x1b[1J", b"\x1b[2J", b"\x1b[3J"):
            with self.subTest(sequence):
                with self.assertRaises(ValueError):
                    self.render(b"\x1b[1;1Hkeep" + sequence)
        self.assertEqual(self.render(b"\x1b[1;1Hkeep\x1b[1;3H\x1b[0K")[0], "ke")

    def test_screen_refuses_sequences_and_controls_it_does_not_model(self):
        for sequence in (
                b"\x1b[2D", b"\x1b[1A", b"\x1b[B", b"\x1b[3C",  # cursor moves
                b"\x1b[5G", b"\x1b[3d", b"\x1b[?5H",
                b"\x1b[1;20r",  # scroll region
                b"\x1b[2L", b"\x1b[2M", b"\x1b[2@", b"\x1b[2P", b"\x1b[2X",
                b"\x1b[2S", b"\x1b[2T",  # scroll up and down
                b"\x1b[38:2::1:2:3m", b"\x1b[?7l", b"\x1b[?1h", b"\x1b[5n",
                b"\x1bM", b"\x1b7", b"\x1b8", b"\x1b=", b"\x1b(B", b"\x1bc",
                b"\x1b]0;title\x1bx",  # an OSC cut short
                b"\b", b"\t", b"\x07", b"\x0b", b"\x0c", b"\x00", b"\x7f"):
            with self.subTest(sequence):
                with self.assertRaises(ValueError):
                    self.render(b"\x1b[1;1Hkeep" + sequence + b"more")
        with self.assertRaises(ValueError):
            self.render(b"\x1b[1;1Habc\x1b[2Dx\x1b[2;1Hone\ttwo\bX\x1b[1Aup",
                        rows=3, cols=20)

    def test_screen_renders_through_the_sequences_codex_sends(self):
        # Every form tty.log of runs 2c-2f holds, besides H, K, J and SGR.
        quiet = [b"\x1b[?%d%s" % (mode, end) for mode in (
            25, 1000, 1002, 1003, 1004, 1006, 1007, 1015, 1049, 2004, 2026)
            for end in (b"h", b"l")]
        quiet += [b"\x1b[0 q", b"\x1b[<u", b"\x1b[<1u", b"\x1b[>7u",
                  b"\x1b[?u", b"\x1b[c", b"\x1b[6n", b"\x1b[>4;0m",
                  b"\x1b]0;title\x07", b"\x1b]8;;https://example.com\x07",
                  b"\x1b]10;?\x1b\\", b"\x1b]777;notify;Codex;done\x1b\\"]
        lines = self.render(b"\x1b[2;3H" + b"".join(quiet) + b"hello"
                            b"\x1b[38;5;8m!\x1b[39m" + b"".join(quiet))
        self.assertEqual(lines[1], "  hello!")

    def test_screen_moves_the_cursor_on_carriage_return_and_line_feed(self):
        self.assertEqual(self.render(b"one\r\ntwo\rT\nx", rows=3),
                         ["one", "Two", " x"])
        self.assertEqual(self.render(b"a\r\nb\r\nc", rows=2), ["b", "c"])

    def test_screen_joins_sequences_split_across_reads(self):
        screen = self.driver.Screen(6, 30)
        for chunk in (b"\x1b[2;", b"3H\xe2\x80", b"\xba High", b"\x1b", b"[K",
                      b"\x1b]10;?\x1b", b"\\\x1b]0;ti", b"tle\x07\x1b[?20",
                      b"26l"):
            screen.feed(chunk)
        self.assertEqual(screen.lines()[1], "  › High")
        screen.feed(b"\x1b")
        with self.assertRaises(ValueError):  # a cut ESC M is refused too
            screen.feed(b"M")

    # Screens as Codex 0.167.0 rendered them (rows trimmed, path shortened).
    READY = [
        "  >_ OpenAI Codex (v0.167.0)",
        "⚠ Heads up, this line stands in for a startup notice.",
        "› Ask Codex to do anything",
        "",
        "  GPT-6.1-Sol low · ~/dev/subspace",
        "  ← for agents · ? for shortcuts                ⚠ 2 warnings · f2 to view",
    ]
    UPDATE = [
        "  Update available · 0.166.0 → 0.167.0",
        "  Release notes: https://github.com/openai/codex/releases/latest",
        "› 1. Update now (runs `brew upgrade --cask codex`)",
        "  2. Skip",
        "  3. Skip until next version",
        "  enter",
    ]
    WORKING = [
        "› Run echo one with your shell tool.",
        "• Working (3s • esc to interrupt)",
        "  GPT-6.1-Sol low · ~/dev/subspace",
    ]

    MODELS = [
        "  Select Model and Effort",
        "",
        "› 1. GPT-6.1-Sol (current)  Latest workhorse model for coding and everyday work.",
        "  2. GPT-6-Astra            Frontier intelligence for the most demanding work.",
        "  8. GPT-5.6-Luna           Older fast and efficient model.",
        "",
        "  enter select · esc back",
    ]
    EFFORTS = [
        "  Select Reasoning Level for GPT-6.1-Sol",
        "",
        "› 1. Low (default) (current)  Fast responses with lighter reasoning",
        "  2. Medium                   Balances speed and reasoning depth for everyday tasks",
        "  3. High                     Greater reasoning depth for complex problems",
        "  4. Extra high               Extra high reasoning depth for complex problems",
        "  5. More reasoning…          Max and Ultra consume usage limits faster",
        "",
        "  enter default · s session · esc back",
    ]

    def test_picker_reads_title_options_and_highlight(self):
        self.assertEqual(self.driver.picker(self.EFFORTS), (
            "Select Reasoning Level for GPT-6.1-Sol",
            ["Low (default) (current)", "Medium", "High", "Extra high",
             "More reasoning…"],
            0,
            "enter default · s session · esc back",
        ))
        moved = [line.replace("›", " ") for line in self.EFFORTS]
        moved[4] = "› " + moved[4][2:]
        self.assertEqual(self.driver.picker(moved)[2], 2)
        self.assertEqual(self.driver.picker(self.MODELS)[:2], (
            "Select Model and Effort",
            ["GPT-6.1-Sol (current)", "GPT-6-Astra", "GPT-5.6-Luna"]))
        self.assertEqual(self.driver.screen_state(self.EFFORTS), "picker")
        self.assertIsNone(self.driver.picker(self.READY))

    def test_picker_key_walks_to_the_option_then_confirms(self):
        key = self.driver.picker_key
        title = "Select Reasoning Level for"
        self.assertEqual(key(self.EFFORTS, title, "High", "s"), "\x1b[B")
        on_high = [line.replace("›", " ") for line in self.EFFORTS]
        on_high[4] = "› " + on_high[4][2:]
        self.assertEqual(key(on_high, title, "High", "s"), "s")
        self.assertEqual(key(on_high, title, "Low", "s"), "\x1b[A")
        self.assertEqual(key(self.MODELS, "Select Model and Effort",
                             "GPT-6.1-Sol", "\r"), "\r")

    def test_picker_key_refuses_update_offer_and_unknown_screens(self):
        key = self.driver.picker_key
        for lines, title, label, confirm in (
                (self.UPDATE, "Select Reasoning Level for", "High", "s"),
                (self.UPDATE, "Update available", "Update now", "\r"),
                (self.MODELS, "Select Reasoning Level for", "High", "s"),
                # Another picker that holds the label and offers the key.
                (self.MODELS, "Select Reasoning Level for", "GPT-6.1-Sol", "\r"),
                (self.EFFORTS, "Select Reasoning Level for", "Ultra", "s"),
                (self.READY, "Select Model and Effort", "GPT-6.1-Sol", "\r"),
                # Enter here sets the global default in config.toml.
                (self.EFFORTS, "Select Reasoning Level for", "Low", "\r")):
            with self.subTest(lines=lines[0], label=label, confirm=confirm):
                with self.assertRaises(RuntimeError):
                    key(lines, title, label, confirm)

    def test_screen_state_tells_idle_composer_from_update_offer(self):
        self.assertEqual(self.driver.screen_state(self.READY), "ready")
        self.assertEqual(self.driver.screen_state(self.UPDATE), "update")
        self.assertIsNone(self.driver.screen_state(self.WORKING))


class FakeTty:
    """The driver's end of the pseudo-terminal: keys go into a pipe, and the
    screen is what `render` makes of all keys sent so far."""

    def __init__(self, render, react=None):
        self.r, self.w = os.pipe()
        os.set_blocking(self.r, False)
        self.render = render
        self.react = react
        self.keys = ""

    def settle(self, *args, **kwargs):
        try:
            self.keys += os.read(self.r, 65536).decode()
        except BlockingIOError:
            pass
        if self.react:
            self.react(self.keys)

    def lines(self):
        return self.render(self.keys)

    def close(self):
        os.close(self.r)
        os.close(self.w)


class FakeClock:
    """The driver's clock: time passes only when the driver waits, and each
    wait lets the fake terminal take the keys sent so far."""

    def __init__(self, tty):
        self.tty = tty
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    def time_ns(self):
        return int(self.now * 1e9)

    def sleep(self, seconds):
        self.now += seconds
        self.tty.settle()


def composer(text):
    """The screen with `text` typed into the composer, as Codex 0.167.0
    drew it: wrapped, no `? for shortcuts` in the footer."""
    rows = textwrap.wrap(text, 116)
    return [
        "  >_ OpenAI Codex (v0.167.0)",
        "› This is an earlier prompt, kept in the history.",
        "",
        "› " + rows[0], *("  " + row for row in rows[1:]),
        "",
        "  GPT-6.1-Sol low · ~/dev/subspace",
        "  " + " " * 90 + "⚠ 2 warnings · f2 to view",
    ]


def popup(highlight, typed):
    """The slash command popup under `typed`, highlighting `highlight`."""
    rows = {"/model": "choose what model and reasoning effort to use",
            "/status": "show current session configuration and token usage",
            "/statusline": "configure which items appear in the status line",
            "/exit": "exit Codex"}
    shown = [name for name in rows if name.startswith(typed)]
    return [
        *("%s %-11s  %s" % ("›" if name == highlight else " ", name, rows[name])
          for name in shown),
        "",
        "› " + typed,
        "",
        "  GPT-6.1-Sol low · ~/dev/subspace",
        "",
    ]


def ready(effort):
    """The idle composer, the status line showing `effort`."""
    return [line.replace("GPT-6.1-Sol low", "GPT-6.1-Sol " + effort)
            for line in DriverScreenTests.READY]


OPTION = re.compile(r"^(›| ) \d+\. ")


def highlight(screen, index):
    """A picker screen with option `index` highlighted."""
    rows = [i for i, line in enumerate(screen) if OPTION.match(line)]
    return [("›" if i == rows[index] else " ") + line[1:] if i in rows else line
            for i, line in enumerate(screen)]


UNEXPECTED = ["  (a screen for keys this fake Codex does not expect)"]
DOWN = "\x1b[B"


def scripted(steps):
    """A fake Codex screen: the idle composer before any key, then one step
    after the other: (keys, the screen while they are typed or None, the
    screen once they are all in). Keys off the script show an unexpected
    screen."""
    def render(keys):
        screen = DriverScreenTests.READY
        for step, typing, after in steps:
            if keys.startswith(step):
                keys, screen = keys[len(step):], after
            elif keys and typing and step.startswith(keys):
                return typing(keys)
            else:
                break
        return UNEXPECTED if keys else screen
    return render


def exited_child():
    """A child that has exited but is not yet reaped: what the driver's wait
    for the end of Codex finds after /exit."""
    pid = os.posix_spawn("/usr/bin/true", ["true"], {})
    os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
    return pid


def reap(pid):
    """Reaps a child the driver left (a run that aborted before /exit)."""
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def typing_command(name):
    return lambda typed: popup(name, typed)


def model_steps(models=None, after="high"):
    """/model: keep the current model, then Low → High for this session."""
    efforts = DriverScreenTests.EFFORTS
    return [
        ("/model\r", typing_command("/model"), models or DriverScreenTests.MODELS),
        ("\r", None, highlight(efforts, 0)),
        (DOWN, None, highlight(efforts, 1)),
        (DOWN, None, highlight(efforts, 2)),
        ("s", None, ready(after)),
    ]


class DriverKeyTests(unittest.TestCase):
    """Run 2f presses a key only on a screen it has checked."""

    PROMPT = ("This is a capture workload for reasoning effort. Run exactly "
              "this one shell command with your shell tool and nothing else: "
              "echo one. Then reply with its output.")

    def setUp(self):
        self.driver = load_driver()
        self.actions, self.stops = [], []

        def action(what, **extra):
            self.actions.append(what)
            if what == "saw Stop":
                self.stops.append(extra["turn_id"])
        self.driver.action = action
        # Never the real spool, should a key slip through to a prompt's wait.
        spool = tempfile.TemporaryDirectory()
        self.addCleanup(spool.cleanup)
        self.driver.EVENTS = spool.name

    def session(self, render, react=None):
        tty = FakeTty(render, react)
        self.addCleanup(tty.close)
        clock = FakeClock(tty)
        self.driver.time = clock
        s = self.driver.Session.__new__(self.driver.Session)
        s.fd, s.screen, s.screen_failed, s.out = tty.w, tty, False, b""
        s.session_id, s.update_skipped = None, False
        s.settle = lambda quiet=3, timeout=60: clock.sleep(quiet)
        return s, tty

    def sent(self, tty):
        tty.settle()
        return tty.keys

    def test_wait_ready_skips_the_update_offer_with_esc(self):
        s, tty = self.session(
            lambda keys: DriverScreenTests.READY if "\x1b" in keys
            else DriverScreenTests.UPDATE)
        s.wait_ready(timeout=2)
        self.assertEqual(self.sent(tty), "\x1b")

    def test_wait_ready_answers_a_staying_update_offer_once_then_aborts(self):
        s, tty = self.session(lambda keys: DriverScreenTests.UPDATE)
        with self.assertRaises(RuntimeError):
            s.wait_ready(timeout=2)
        self.assertEqual(self.sent(tty), "\x1b")

    def test_wait_ready_aborts_when_the_update_offer_returns_in_the_session(self):
        returned = [False]
        s, tty = self.session(
            lambda keys: DriverScreenTests.UPDATE if returned[0] or not keys
            else DriverScreenTests.READY)
        s.wait_ready(timeout=2)
        returned[0] = True
        with self.assertRaises(RuntimeError):
            s.wait_ready(timeout=2)
        self.assertEqual(self.sent(tty), "\x1b")

    def test_wait_ready_aborts_on_a_screen_that_stays_unknown(self):
        s, tty = self.session(lambda keys: DriverScreenTests.WORKING)
        with self.assertRaises(RuntimeError):
            s.wait_ready(timeout=0.3)
        self.assertEqual(self.sent(tty), "")
        self.assertIn("unknown screen", self.actions)

    def test_command_presses_enter_when_the_popup_highlights_it(self):
        for name in ("/status", "/exit"):
            with self.subTest(name=name):
                s, tty = self.session(
                    lambda keys, name=name: popup(name, keys) if keys
                    else DriverScreenTests.READY)
                s.command(name)
                self.assertEqual(self.sent(tty), name + "\r")

    def test_command_refuses_enter_when_the_popup_highlights_another(self):
        s, tty = self.session(
            lambda keys: popup("/statusline", keys) if keys
            else DriverScreenTests.READY)
        with self.assertRaises(RuntimeError):
            s.command("/status")
        self.assertEqual(self.sent(tty), "/status")

    def test_quit_refuses_enter_without_the_exit_popup(self):
        s, tty = self.session(
            lambda keys: composer(keys) if keys else DriverScreenTests.READY)
        with self.assertRaises(RuntimeError):
            s.quit()
        self.assertEqual(self.sent(tty), "/exit")

    def test_submit_presses_enter_when_the_composer_shows_the_prompt(self):
        s, tty = self.session(
            lambda keys: composer(keys) if keys else DriverScreenTests.READY)
        s.submit(self.PROMPT)
        self.assertEqual(self.sent(tty), self.PROMPT + "\r")

    def test_submit_refuses_enter_on_any_other_screen(self):
        dialog = ["  Would you like to run the following command?",
                  "› 1. Yes, proceed (y)"]
        for name, after in (
                ("prompt cut off", lambda keys: composer(keys[:-8])),
                ("composer empty", lambda keys: DriverScreenTests.READY),
                ("update offer", lambda keys: DriverScreenTests.UPDATE + composer(keys)),
                ("picker", lambda keys: DriverScreenTests.EFFORTS + composer(keys)),
                ("dialog", lambda keys: dialog + composer(keys))):
            with self.subTest(name):
                s, tty = self.session(
                    lambda keys, after=after: after(keys) if keys
                    else DriverScreenTests.READY)
                with self.assertRaises(RuntimeError):
                    s.submit(self.PROMPT)
                self.assertEqual(self.sent(tty), self.PROMPT)

    def test_command_and_submit_type_nothing_until_the_composer_is_ready(self):
        for name, screen, keys in (("update offer", DriverScreenTests.UPDATE, "\x1b"),
                                   ("busy", DriverScreenTests.WORKING, "")):
            for call in ("command", "submit"):
                with self.subTest(name, call=call):
                    s, tty = self.session(lambda keys, screen=screen: screen)
                    with self.assertRaises(RuntimeError):
                        if call == "command":
                            s.command("/status")
                        else:
                            s.submit(self.PROMPT)
                    self.assertEqual(self.sent(tty), keys)

    def test_switch_effort_sets_the_effort_for_this_session_only(self):
        s, tty = self.session(scripted(model_steps()))
        s.switch_effort("High")
        self.assertEqual(self.sent(tty), "/model\r" "\r" + DOWN + DOWN + "s")

    def test_switch_effort_needs_exactly_one_current_model(self):
        models = DriverScreenTests.MODELS
        for name, shown in (
                ("none", [line.replace(" (current)", " " * 10) for line in models]),
                ("two", [line.replace("GPT-6-Astra" + " " * 10, "GPT-6-Astra (current)")
                         for line in models])):
            with self.subTest(name):
                s, tty = self.session(scripted(model_steps(shown)))
                with self.assertRaises(RuntimeError):
                    s.switch_effort("High")
                self.assertEqual(self.sent(tty), "/model\r")

    def test_switch_effort_aborts_when_the_status_line_keeps_the_old_effort(self):
        s, tty = self.session(scripted(model_steps(after="low")))
        with self.assertRaises(RuntimeError):
            s.switch_effort("High")
        self.assertEqual(self.sent(tty), "/model\r" "\r" + DOWN + DOWN + "s")

    def spool(self, **payload):
        """Writes one envelope as the plugin's hook would, at the fake time."""
        path = os.path.join(self.driver.EVENTS, "%03d.json" % len(os.listdir(self.driver.EVENTS)))
        with open(path, "w") as f:
            json.dump({"payload": payload}, f)
        now = self.driver.time.time_ns()
        os.utime(path, ns=(now, now))

    def effort_session(self, cut=None, exit_popup=True):
        """Run 2f against a fake Codex modelled on the 0.167.0 screens: each
        submitted prompt is one turn ending with its root Stop, turn 3 with a
        subagent. `cut`: the composer shows that turn's prompt cut off;
        `exit_popup=False`: /exit stays plain composer text."""
        prompts = self.driver.EFFORT_PROMPTS
        done = set()

        def codex(keys):
            for turn, text in enumerate(prompts):
                if turn in done or text + "\r" not in keys:
                    continue
                done.add(turn)
                event = dict(session_id="fake-session", turn_id="turn-%d" % turn,
                             cwd=self.driver.REPO)
                self.spool(hook_event_name="UserPromptSubmit", **event)
                if turn == 2:
                    self.spool(hook_event_name="SubagentStart", agent_id="child", **event)
                    self.spool(hook_event_name="SubagentStop", agent_id="child", **event)
                self.spool(hook_event_name="Stop", **event)

        def typing_prompt(turn):
            return (lambda typed: composer(typed[:-8])) if turn == cut else composer
        steps = [
            ("/status\r", typing_command("/status"), ready("low")),
            (prompts[0] + "\r", typing_prompt(0), ready("low")),
            *model_steps(),
            ("/status\r", typing_command("/status"), ready("high")),
            (prompts[1] + "\r", typing_prompt(1), ready("high")),
            (prompts[2] + "\r", typing_prompt(2), ready("high")),
            ("/exit\r", typing_command("/exit") if exit_popup else composer, []),
        ]
        s, tty = self.session(scripted(steps), react=codex)
        s.pid = exited_child()
        self.addCleanup(reap, s.pid)
        return s, tty

    def effort_keys(self):
        """Every key of run 2f, in order."""
        p = self.driver.EFFORT_PROMPTS
        return ("/status\r" + p[0] + "\r" + "/model\r" "\r" + DOWN + DOWN + "s"
                + "/status\r" + p[1] + "\r" + p[2] + "\r" + "/exit\r")

    def test_effort_run_reads_every_screen_before_its_keys(self):
        s, tty = self.effort_session()
        self.driver.effort_run(s)
        self.assertEqual(self.sent(tty), self.effort_keys())
        self.assertEqual(self.stops, ["turn-0", "turn-1", "turn-2"])
        self.assertEqual(s.session_id, "fake-session")
        self.assertIn("exited", self.actions)

    def test_effort_run_sends_no_prompt_the_composer_does_not_show(self):
        for turn, text in enumerate(self.driver.EFFORT_PROMPTS):
            with self.subTest(turn=turn):
                s, tty = self.effort_session(cut=turn)
                with self.assertRaises(RuntimeError):
                    self.driver.effort_run(s)
                keys = self.effort_keys()
                self.assertEqual(self.sent(tty), keys[:keys.index(text) + len(text)])

    def test_effort_run_leaves_only_through_the_exit_popup(self):
        s, tty = self.effort_session(exit_popup=False)
        with self.assertRaises(RuntimeError):
            self.driver.effort_run(s)
        self.assertEqual(self.sent(tty), self.effort_keys()[:-1])

    def test_a_failing_screen_model_neither_stops_draining_nor_types(self):
        class Broken:
            def feed(self, data):
                raise ValueError("unknown sequence")

            def lines(self):
                raise AssertionError("read a broken screen")
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        s = self.driver.Session.__new__(self.driver.Session)
        s.fd, s.screen, s.screen_failed = r, Broken(), False
        s.log, s.out, s.last_output = io.BytesIO(), b"", 0
        s.stop = threading.Event()
        drain = threading.Thread(target=s._drain, daemon=True)
        drain.start()
        os.write(w, b"one")
        deadline = time.time() + 2
        while b"one" not in s.out and time.time() < deadline:
            time.sleep(0.01)
        os.write(w, b"two")
        os.close(w)
        drain.join(2)
        self.assertFalse(drain.is_alive())
        self.assertEqual(s.log.getvalue(), b"onetwo")
        self.assertEqual(s.out, b"onetwo")
        self.assertEqual(self.actions, ["screen model failed"])
        self.assertIsNone(self.driver.screen_state(s.lines()))
        s.settle = lambda *args, **kwargs: None
        with self.assertRaises(RuntimeError):
            s.wait_ready(timeout=0.3)
        self.assertIn("unknown screen", self.actions)

    def test_an_erase_mode_the_screen_cannot_model_aborts_the_run(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        s = self.driver.Session.__new__(self.driver.Session)
        s.fd, s.screen, s.screen_failed = r, self.driver.Screen(6, 120), False
        s.log, s.out, s.last_output = io.BytesIO(), b"", 0
        s.stop = threading.Event()
        drain = threading.Thread(target=s._drain, daemon=True)
        drain.start()
        for row, line in enumerate(DriverScreenTests.READY, 1):
            os.write(w, b"\x1b[%d;1H" % row + line.encode())
        os.write(w, b"\x1b[2J")  # erases the whole screen, not from the cursor
        os.close(w)
        drain.join(2)
        self.assertEqual(self.actions, ["screen model failed"])
        s.settle = lambda *args, **kwargs: None
        with self.assertRaises(RuntimeError):
            s.wait_ready(timeout=0.3)
        self.assertIn("unknown screen", self.actions)


if __name__ == "__main__":
    unittest.main()
