#!/usr/bin/env python3
"""Plays the runs S1-S25 of README.md without a human (#58).

Starts watch-sessions.py, then drives interactive `claude` sessions in a
pseudo-terminal: types prompts, presses Enter, Esc and Ctrl-C, and waits for
the hook events in captures/events/ (never for the status file under test).
S22 and S23 are the exceptions: S22 starts a background session with
`claude --bg`, S23 also repeats `claude -p`, both as plain subprocesses
without a pseudo-terminal. S24 starts a background session the same way and
drives `claude attach <job>` in the pseudo-terminal.
Every action goes to captures/sessions/actions.jsonl with wall-clock ms, the
terminal output of each run to captures/tty/<run>.log. Runs collect.sh at
the end. Uses haiku (some runs sonnet, S25 because haiku sends no effort);
costs a few cents.

Usage: ./drive-session-runs.py [S1 S2 …]   (default: all)
"""
import fcntl
import json
import os
import pty
import re
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(HERE, "captures")
EVENTS = os.path.join(CAPTURES, "events")
SESSIONS_OUT = os.path.join(CAPTURES, "sessions")
TTY = os.path.join(CAPTURES, "tty")
MODEL = "haiku"
ESC, CTRL_C, ENTER = "\x1b", "\x03", "\r"
KILL_AGENTS = "\x18\x0b"  # ctrl+x ctrl+k, twice: stop all background agents
ANSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]|\s")
# Startup dialogs answered with their default (Enter). Anything else fails.
DIALOGS = (b"AllowexternalCLAUDE.mdfileimports",)
EXIT_DIALOG = b"Backgroundworkisrunning"  # on /exit; default stops the tasks
LIVE = []  # sessions to kill if a run fails
# The terminal identifiers the plugin copies (contract §4); never other env values.
TERMINAL_NAMES = ("TERM_PROGRAM", "TERM_PROGRAM_VERSION", "__CFBundleIdentifier",
                  "TERM_SESSION_ID", "ITERM_SESSION_ID", "WARP_FOCUS_URL",
                  "WARP_TERMINAL_SESSION_UUID", "WEZTERM_PANE", "KITTY_WINDOW_ID",
                  "KITTY_LISTEN_ON", "TMUX", "TMUX_PANE")
CONFIG = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def now_ms():
    return time.time_ns() // 1_000_000


def clean_env():
    """This script may run inside Claude Code; the runs must not notice."""
    drop = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_PID", "CLAUDE_JOB_DIR",
            "CLAUDE_EFFORT", "AI_AGENT")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def action(run, what, **extra):
    entry = {"ms": now_ms(), "run": run, "action": what, **extra}
    with open(os.path.join(SESSIONS_OUT, "actions.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def wait_event(name, since_ms, timeout, pred=None):
    """The first hook event `name` whose file appeared after since_ms."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for n in sorted(os.listdir(EVENTS)) if os.path.isdir(EVENTS) else []:
            if not n.endswith(".json"):
                continue
            p = os.path.join(EVENTS, n)
            try:
                if os.stat(p).st_mtime_ns // 1_000_000 < since_ms:
                    continue
                with open(p) as f:
                    ev = json.load(f)
            except (OSError, ValueError):
                continue
            if ev.get("hook_event_name") == name and (pred is None or pred(ev)):
                return ev
        time.sleep(0.2)
    raise TimeoutError(f"no {name} within {timeout}s")


class Session:
    def __init__(self, run, args=(), model=MODEL, env=None, cmd=None):
        """cmd replaces `claude --model <model> <args>` (S24: `claude attach <job>`)."""
        self.run = run
        argv = cmd or ["claude", "--model", model, *args]
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(HERE)
            os.execvpe(argv[0], argv, {**clean_env(), **(env or {})})
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self.log = open(os.path.join(TTY, f"{run}.log"), "ab")
        self.out, self.total, self.lock = b"", 0, threading.RLock()  # re-entrant: keep_since() calls since()
        LIVE.append(self)
        threading.Thread(target=self._drain, daemon=True).start()
        self.started = now_ms()
        action(run, "start", pid=self.pid,
               **({"cmd": cmd} if cmd else {"model": model, "args": list(args)}))

    def _drain(self):
        while True:
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                return
            if not data:
                return
            self.log.write(data)
            self.log.flush()
            self.add(ANSI.sub(b"", data))

    def add(self, text):
        """Appends drawn text to out (its last 20000 bytes); total counts every byte added.

        Runs on the drain thread, under lock: since() and the rewrites of out on
        the main thread see an add() whole or not at all, and lose none.
        """
        with self.lock:
            self.total += len(text)
            self.out = (self.out + text)[-20000:]

    def since(self, pos):
        """out from the total pos on; all of out if the trim already dropped pos.

        Reads total and out under lock, so both are of the same moment.
        Text removed from out (ready()'s drop()) moves the cut earlier: more kept, never less.
        If more than 20000 bytes are drawn after pos before it is used, the oldest of
        them are already gone from out (add()'s limit); since() then keeps all of out.
        """
        with self.lock:
            return self.out[max(0, pos - (self.total - len(self.out))):]

    # The rewrites of out: under lock, so text the drain thread adds meanwhile is kept.
    def keep_since(self, pos):
        """Keeps only since(pos) in out."""
        with self.lock:
            self.out = self.since(pos)

    def keep_from(self, find):
        """Keeps out from the index find(out) returns on; all of it if that is negative."""
        with self.lock:
            i = find(self.out)
            if i >= 0:
                self.out = self.out[i:]

    def drop(self, text):
        """Removes every occurrence of text from out."""
        with self.lock:
            self.out = self.out.replace(text, b"")

    def clear(self):
        with self.lock:
            self.out = b""

    def keys(self, what, keys):
        os.write(self.fd, keys.encode())
        action(self.run, what, pid=self.pid)

    def send(self, text):
        os.write(self.fd, text.encode())
        time.sleep(0.5)
        os.write(self.fd, ENTER.encode())
        action(self.run, "send", pid=self.pid, text=text)
        return now_ms() - 1000

    def wait(self, name, since, timeout=90, pred=None):
        ev = wait_event(name, since, timeout, pred)
        action(self.run, f"saw {name}", pid=self.pid)
        return ev

    def ready(self):
        """Waits for SessionStart, answering DIALOGS; returns it and the total (Session.add)
        just before the last Enter on one, for since() (None if none was answered)."""
        deadline, answered = time.time() + 60, None
        while True:
            try:
                start = self.wait("SessionStart", self.started, 1)
                break
            except TimeoutError:
                if time.time() > deadline:
                    raise
            for d in DIALOGS:
                if d in self.out:
                    self.drop(d)
                    # Taken before the Enter: the drain thread may add what the TUI
                    # draws after it while keys() still runs, and that must count.
                    pos = self.total
                    self.keys(f"dialog {d.decode()}: default", ENTER)
                    answered = pos
        time.sleep(3)
        return start, answered

    def exit(self):
        self.clear()
        self.send("/exit")
        time.sleep(2)
        if EXIT_DIALOG in self.out:
            self.keys("exit dialog: stop background tasks", ENTER)
        self.reap(30)

    def exit_hard(self):
        os.kill(self.pid, signal.SIGTERM)
        action(self.run, "kill -TERM", pid=self.pid)
        self.reap(10)

    def reap(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                LIVE.remove(self)
                action(self.run, "exited", pid=self.pid, status=status)
                return
            time.sleep(0.2)
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        LIVE.remove(self)
        action(self.run, "killed after timeout", pid=self.pid)


def s1():
    s = Session("S1")
    s.ready()
    s.wait("Stop", s.send("hi"))
    time.sleep(5)
    s.exit()


def s2():
    s = Session("S2")
    s.ready()
    story = "Write a 2000-word story about a lighthouse. No tools."
    for name, key in (("esc", ESC), ("ctrl-c", CTRL_C)):
        s.wait("UserPromptSubmit", s.send(story))
        time.sleep(4)
        s.keys(f"press {name} mid-turn", key)
        time.sleep(5)
    s.exit()


def s3():
    s = Session("S3", ["--allowedTools", "Bash(sleep 20; echo done)"])
    s.ready()
    t = s.send("Run exactly this Bash command and nothing else: sleep 20; echo done")
    s.wait("PreToolUse", t, pred=lambda e: e.get("tool_name") == "Bash")
    time.sleep(4)
    s.keys("press esc mid-tool", ESC)
    time.sleep(5)
    s.exit()


def s4():
    s = Session("S4")
    s.ready()
    t = s.send("Run exactly this Bash command and nothing else: touch captures/perm-one")
    s.wait("PermissionRequest", t)
    time.sleep(15)
    s.keys("approve permission", ENTER)
    s.wait("Stop", t)
    time.sleep(3)
    t = s.send("Run exactly this Bash command and nothing else: touch captures/perm-two")
    s.wait("PermissionRequest", t)
    time.sleep(15)
    s.keys("reject permission", ESC)
    time.sleep(5)
    t = s.send("Use the AskUserQuestion tool to ask me which color I like, "
               "with the two options red and blue. Then reply with my answer.")
    s.wait("PreToolUse", t, pred=lambda e: e.get("tool_name") == "AskUserQuestion")
    time.sleep(15)
    s.keys("answer question", ENTER)
    try:
        s.wait("PostToolUse", t, 5, lambda e: e.get("tool_name") == "AskUserQuestion")
    except TimeoutError:
        s.keys("submit answer", ENTER)
    s.wait("Stop", t)
    time.sleep(5)
    s.exit()


def s5():
    s = Session("S5")
    s.ready()
    s.keys("enter bash mode", "!")
    time.sleep(1)
    s.send("sleep 10")
    time.sleep(15)
    s.exit()


def s6():
    s = Session("S6", ["--allowedTools", "Agent",
                       "Bash(sleep 10; echo fg)", "Bash(sleep 30; echo bg)"], model="sonnet")
    s.ready()
    t = s.send("Call the Agent tool once with subagent_type general-purpose and "
               "run_in_background false, prompt: 'Run exactly this Bash command in the "
               "foreground: sleep 10; echo fg. Report the output.' Then reply with its result.")
    s.wait("Stop", t, 180)
    time.sleep(3)
    t = s.send("Call the Agent tool once with subagent_type general-purpose and "
               "run_in_background true, prompt: 'Run exactly this Bash command in the "
               "foreground: sleep 30; echo bg. Report the output.' Don't wait for it.")
    s.wait("Stop", t, 120)
    # 2.1.287 hands results back as <agent-message …>, 2.1.285 as <task-notification>
    n = s.wait("UserPromptSubmit", t, 180, lambda e: str(e.get("prompt", "")).startswith(
        ("<task-notification>", "<agent-message")) and "sleep 30" in str(e.get("prompt")))
    s.wait("Stop", t, 120, lambda e: e.get("prompt_id") == n.get("prompt_id"))
    time.sleep(10)
    s.exit()


def s7():
    s = Session("S7", ["--continue"])
    s.ready()
    s.wait("Stop", s.send("hi"))
    time.sleep(5)
    s.exit()


def s8():
    s = Session("S8")
    s.ready()
    s.wait("Stop", s.send("hi"))
    time.sleep(3)
    os.kill(s.pid, signal.SIGKILL)
    action("S8", "kill -9", pid=s.pid)
    s.reap(10)
    time.sleep(10)


def s9():
    action("S9", "start claude -p")
    p = subprocess.run(["claude", "-p", "hi", "--model", MODEL], cwd=HERE, env=clean_env(),
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    action("S9", "exited", status=p.returncode)
    time.sleep(10)


def s10():
    """CLAUDE_CONFIG_DIR, without a login: does the status file move with it?"""
    cfg = os.path.join(CAPTURES, "s10-config")
    shutil.rmtree(cfg, ignore_errors=True)
    os.makedirs(cfg)
    watcher = subprocess.Popen(
        [os.path.join(HERE, "watch-sessions.py")], stdout=subprocess.DEVNULL,
        env={**os.environ, "CLAUDE_CONFIG_DIR": cfg,
             "WATCH_SESSIONS_OUT": os.path.join(CAPTURES, "sessions-s10")})
    time.sleep(1)
    s = Session("S10", env={"CLAUDE_CONFIG_DIR": cfg})
    time.sleep(20)  # onboarding without a login; no prompt possible
    in_cfg = sorted(os.listdir(os.path.join(cfg, "sessions"))) if os.path.isdir(
        os.path.join(cfg, "sessions")) else None
    default = os.path.exists(os.path.expanduser(f"~/.claude/sessions/{s.pid}.json"))
    action("S10", "checked", pid=s.pid, config_sessions=in_cfg, default_sessions_has_pid=default)
    s.exit_hard()
    time.sleep(2)
    watcher.terminate()
    watcher.wait()


def s11():
    s = Session("S11")
    s.ready()
    time.sleep(5)
    s.exit()


def s12():
    s = Session("S12", ["--allowedTools", "Bash(ls captures/nonexistent-dir)"])
    s.ready()
    t = s.send("Run exactly this Bash command and nothing else: ls captures/nonexistent-dir")
    try:
        s.wait("PermissionRequest", t, 20)
        s.keys("approve permission", ENTER)
    except TimeoutError:
        pass
    s.wait("Stop", t)
    time.sleep(5)
    s.exit()


def s13():
    s = Session("S13", ["--allowedTools", "Write", "Edit", "Read", "Grep", "Glob"])
    s.ready()
    s.wait("Stop", s.send(
        "In this order, one tool call each: Write the file captures/s13.txt with the text "
        "'one'. Edit it to replace 'one' with 'two'. Read it. Grep for 'two' with path "
        "captures/s13.txt. Glob for 'captures/s13*'. Then reply 'done'."), 180)
    time.sleep(5)
    s.exit()


def s14():
    """Ended from outside without any input: SessionEnd has no prompt_id."""
    s = Session("S14")
    s.ready()
    time.sleep(5)
    s.exit_hard()
    time.sleep(5)


def s15():
    """A background agent stopped by the user (#67): no SubagentStop follows."""
    steps = [f"sleep 10; echo {n}" for n in ("one", "two", "three", "four")]
    s = Session("S15", ["--allowedTools", "Agent", *(f"Bash({c})" for c in steps)], model="sonnet")
    s.ready()
    t = s.send("Call the Agent tool once with subagent_type general-purpose and "
               "run_in_background true, prompt: 'Run these Bash commands one after the "
               "other, each in the foreground: " + ", then ".join(steps) + ". Report the "
               "output.' Don't wait for it.")
    s.wait("Stop", t, 120, lambda e: any(
        isinstance(b, dict) and b.get("type") == "subagent" for b in e.get("background_tasks") or []))
    time.sleep(5)
    for _ in range(2):
        s.keys("press ctrl+x ctrl+k", KILL_AGENTS)
        time.sleep(0.5)
    time.sleep(5)
    ok = "Reply with the word ok. No tools."
    t = s.send(ok)
    n = s.wait("UserPromptSubmit", t, 60, lambda e: e.get("prompt") == ok)
    s.wait("Stop", t, 120, lambda e: e.get("prompt_id") == n.get("prompt_id"))
    time.sleep(60)  # the agent would have finished by now
    s.exit()


def s16():
    """Agent calls with and without the model parameter (#71)."""
    s = Session("S16", ["--allowedTools", "Agent"], model="sonnet")
    s.ready()
    t = s.send("Call the Agent tool twice in one message. First call: subagent_type "
               "general-purpose, model haiku, prompt 'Reply with the word one. No tools.' "
               "Second call: subagent_type general-purpose, no model parameter, prompt "
               "'Reply with the word two. No tools.' Then reply with both results.")
    done = set()
    while len(done) < 2:
        e = s.wait("SubagentStop", t, 180, lambda e: e.get("agent_type") == "general-purpose"
                   and e.get("agent_id") not in done)
        done.add(e.get("agent_id"))
    time.sleep(20)  # hand-back turns
    s.exit()


def s17():
    """/model, then /clear in the same process: which model has the new session (#76)?

    Side effect: /model saves `sonnet` as the default model in the user's
    ~/.claude/settings.json. Reset it by hand afterwards.
    """
    s = Session("S17")
    s.ready()
    s.wait("Stop", s.send("Reply with the word one. No tools."))
    time.sleep(3)
    s.clear()
    t = s.send("/model sonnet")
    time.sleep(2)
    if b"Switchmodel?" in s.out:  # asked once the conversation is cached
        s.keys("switch model dialog: yes", ENTER)
    s.wait("PostModelSwitch", t, 30)
    time.sleep(3)
    s.wait("SessionStart", s.send("/clear"), 30, lambda e: e.get("source") == "clear")
    time.sleep(3)
    s.wait("Stop", s.send("Reply with the word two. No tools."))
    time.sleep(5)
    s.exit()


def s18():
    """--continue S17's session (last on sonnet) with --model haiku (#76)."""
    s = Session("S18", ["--continue"])
    s.ready()
    s.wait("Stop", s.send("Reply with the word three. No tools."))
    time.sleep(5)
    s.exit()


def s19():
    """AskUserQuestion: multiSelect, free text, a note, dismissed with Esc (#13).

    Keys of the question dialog (2.1.316): Enter toggles an option of a
    multiSelect question and picks one of a single-choice question, Tab goes to
    the next question, typing on the last option ("Type something") enters a
    free-text answer, `n` adds a note to an option with a preview, Esc cancels.
    Several questions end on a review screen, submitted with Enter.
    """
    def ask(prompt):
        s.clear()
        t = s.send(prompt)
        s.wait("PreToolUse", t, pred=lambda e: e.get("tool_name") == "AskUserQuestion")
        return t

    def press(what, keys, pause=1):
        s.keys(what, keys)
        time.sleep(pause)

    def dialog(marker):
        deadline = time.time() + 20
        while marker not in s.out:
            if time.time() > deadline:
                raise TimeoutError(f"dialog without {marker.decode()}")
            time.sleep(0.2)

    down = "\x1b[B"
    s = Session("S19", ["--permission-mode", "default"])
    s.ready()
    t = ask('Use the AskUserQuestion tool once with two questions. Question 1: "Which fruits '
            'do you like?", header "Fruits", multiSelect true, options apple, banana, cherry. '
            'Question 2: "Which pet do you prefer?", header "Pet", multiSelect false, options '
            'cat, dog. Then reply with my answers.')
    dialog(b"Whichfruitsdoyoulike?")
    time.sleep(15)  # past the permission_prompt notification
    press("toggle option 1 (apple)", ENTER)
    press("down", down)
    press("down", down)
    press("toggle option 3 (cherry)", ENTER)
    press("next question (tab)", "\t")
    dialog(b"Whichpetdoyouprefer?")
    press("down", down)
    press("down", down)
    press("type free-text answer: a parrot", "a parrot")
    press("confirm free-text answer", ENTER)
    dialog(b"Reviewyouranswers")
    press("submit answers", ENTER)
    s.wait("PostToolUse", t, 20, lambda e: e.get("tool_name") == "AskUserQuestion")
    s.wait("Stop", t)
    time.sleep(3)
    t = ask('Use the AskUserQuestion tool once with one question: "Which layout do you '
            'prefer?", header "Layout", multiSelect false, two options "Grid" and "List", '
            'each with a short ASCII-art preview. Then reply with my answer.')
    dialog(b"pressntoaddnotes")
    time.sleep(3)
    press("down (List)", down)
    press("add note (n)", "n")
    press("type note: more compact please", "more compact please")
    press("pick List with the note", ENTER)
    s.wait("PostToolUse", t, 20, lambda e: e.get("tool_name") == "AskUserQuestion")
    s.wait("Stop", t)
    time.sleep(3)
    ask('Use the AskUserQuestion tool once to ask me "Tea or coffee?", header "Drink", '
        'options tea and coffee. Then reply with my answer.')
    dialog(b"Teaorcoffee?")
    time.sleep(15)
    press("dismiss question (esc)", ESC, 10)
    ok = "Reply with the word ok. No tools."
    t = s.send(ok)
    n = s.wait("UserPromptSubmit", t, 60, lambda e: e.get("prompt") == ok)
    s.wait("Stop", t, 120, lambda e: e.get("prompt_id") == n.get("prompt_id"))
    time.sleep(5)
    s.exit()


def s20():
    """A multi-line Bash command (heredoc) behind a permission prompt (#14)."""
    s = Session("S20", ["--permission-mode", "default"])
    s.ready()
    t = s.send("Make exactly one Bash call and nothing else. Its command has four lines, "
               "keep the line breaks: line 1 cat > captures/s20.txt <<'EOF', line 2 alpha, "
               "line 3 beta, line 4 EOF")
    s.wait("PermissionRequest", t)
    time.sleep(3)
    s.keys("approve permission", ENTER)
    s.wait("PostToolUse", t, 30, lambda e: e.get("tool_name") == "Bash")
    s.wait("Stop", t)
    time.sleep(3)
    s.exit()


def s21():
    """Terminal identifiers in the hooks' environment (#22): the shell's, unchanged?

    Runs in whatever terminal starts the driver; log.sh records the values.
    """
    s = Session("S21")
    s.ready()
    s.wait("Stop", s.send("Reply with the single word ok."))
    time.sleep(3)
    s.exit()


def daemon_processes():
    """Claude Code's background daemon and its pty hosts and spares.

    Only pid, ppid, start time, role and version: the full command lines carry
    home paths and the cwd of whatever session spawned the daemon.
    """
    ps = subprocess.run(["ps", "-axo", "pid=,ppid=,lstart=,command="],
                        capture_output=True, text=True).stdout
    found = []
    for line in ps.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\w+ \w+ +\d+ [\d:]+ \d+)\s+(\S+) (\S+)(.*)", line)
        if not m or os.path.basename(m[4]) != "claude" or not (
                m[5].startswith("bg-") or m[5] == "daemon"):
            continue
        version = re.search(r"/versions/([\d.]+)", m[6])
        found.append({"pid": int(m[1]), "ppid": int(m[2]), "started": m[3], "role": m[5],
                      **({"version": version[1]} if version else {})})
    return found


def s22_jobs(since_ms, run="S22"):
    """Background jobs in this directory started since since_ms, by `claude agents`.

    The fallback when `claude --bg` gave no id, so S22 and S24 can still clean up;
    `run` labels the actions.
    """
    try:
        agents = json.loads(subprocess.run(["claude", "agents", "--json"], env=clean_env(),
                                           stdin=subprocess.DEVNULL, capture_output=True,
                                           text=True, timeout=30).stdout)
    except Exception as e:
        action(run, "claude agents failed", error=str(e))
        return []
    jobs = [a["id"] for a in agents if isinstance(a, dict) and a.get("id")
            and os.path.realpath(a.get("cwd") or "") == HERE
            and isinstance(a.get("startedAt"), int) and a["startedAt"] >= since_ms]
    action(run, "jobs found for cleanup", ids=jobs)
    return jobs


def s22():
    """A background session (`claude --bg`, #27): whose terminal do its hooks see?

    The session runs in a process of Claude Code's daemon, not under this
    driver. Its cwd is this directory, so the project hooks (log.sh) and the
    watcher record it like any other run.
    """
    action("S22", "driver terminal",
           terminal={n: os.environ[n] for n in TERMINAL_NAMES if n in os.environ})
    action("S22", "daemon processes before", processes=daemon_processes())
    started = now_ms()
    bg = None
    try:
        p = subprocess.run(["claude", "--bg", "--model", MODEL, "Reply with the single word ok."],
                           cwd=HERE, env=clean_env(), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        action("S22", "claude --bg", status=p.returncode, stdout=p.stdout, stderr=p.stderr)
        # 2.1.318 prints "backgrounded · <id>" as its first line, then usage hints.
        m = re.search(r"^backgrounded · ([0-9a-f]{8})$", p.stdout, re.M)
        bg = m.group(1) if m else None
        if not bg:
            raise RuntimeError("claude --bg printed no id")
        start = wait_event("SessionStart", started, 90, lambda e: e.get("cwd") == HERE)
        sid = start.get("session_id")
        action("S22", "saw SessionStart", session=sid)
        agents = json.loads(subprocess.run(["claude", "agents", "--json"], env=clean_env(),
                                           stdin=subprocess.DEVNULL, capture_output=True,
                                           text=True, timeout=30).stdout)
        action("S22", "claude agents", entry=[a for a in agents if a.get("id") == bg])
        action("S22", "daemon processes after start", processes=daemon_processes())
        wait_event("Stop", started, 90, lambda e: e.get("session_id") == sid)
        action("S22", "saw Stop", session=sid)
        time.sleep(3)
        logs = subprocess.run(["claude", "logs", bg], env=clean_env(), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=30).stdout
        with open(os.path.join(TTY, "S22.log"), "ab") as f:
            f.write(logs)
    finally:
        # Leave nothing behind in the user's daemon, even after a failure: also
        # when `claude --bg` timed out or printed no id after creating a job.
        jobs = [bg] if bg else s22_jobs(started)
        if not jobs:
            print("S22: no background job found to clean up; check `claude agents`",
                  file=sys.stderr, flush=True)
        for job in jobs:
            for cmd in ("stop", "rm"):  # each on its own: a failed stop must not skip rm
                try:
                    c = subprocess.run(["claude", cmd, job], env=clean_env(),
                                       stdin=subprocess.DEVNULL, capture_output=True,
                                       text=True, timeout=60)
                    action("S22", f"claude {cmd}", id=job, status=c.returncode,
                           stdout=c.stdout, stderr=c.stderr)
                except Exception as e:
                    action("S22", f"claude {cmd} failed", id=job, error=str(e))
                    print(f"S22: claude {cmd} {job} failed ({e}); check `claude agents`",
                          file=sys.stderr, flush=True)
                time.sleep(3)
        action("S22", "daemon processes after cleanup", processes=daemon_processes())


def bg_job_id(stdout):
    """The id `claude --bg` printed: 2.1.318 starts with "backgrounded · <id>"."""
    m = re.search(r"^backgrounded · ([0-9a-f]{8})$", stdout, re.M)
    return m.group(1) if m else None


def status_files_of(sessions, session_id):
    """(name, content) of the status files in sessions/ that carry session_id.

    Reads only *.json; the *.key files next to them are secrets.
    """
    found = []
    try:
        names = sorted(os.listdir(sessions))
    except FileNotFoundError:
        return found
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(sessions, n)) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("sessionId") == session_id:
            found.append((n, doc))
    return found


def session_names(sessions):
    """The names in sessions/, with the hash in key file names masked."""
    try:
        names = os.listdir(sessions)
    except FileNotFoundError:
        return []
    return sorted(re.sub(r"^(\d+)\..+\.key$", r"\1.*.key", n) for n in names)


def terminal_from_ps_env(out):
    """The allowlisted terminal variables in `ps -E` output; every other value is dropped."""
    found = {}
    for token in out.split():
        name, eq, value = token.partition("=")
        if eq and name in TERMINAL_NAMES:
            found[name] = value
    return found


def anonymize(text, home):
    """Home paths (also Claude Code's encoded ones) and per-user temp folders."""
    user = os.path.basename(home)
    text = text.replace(home + "/", "/Users/user/").replace(f"-Users-{user}-", "-Users-user-")
    if text == home:
        text = "/Users/user"
    return re.sub(r"/var/folders/[^/]+/[^/]+/", "/var/folders/<user temp>/", text)


def lsof_open(out, home):
    """Sockets, ttys and files outside /System/, /usr/ and /Library/ in `lsof -F ftn`
    output, paths anonymized.

    Network connections keep only their type: their addresses name the machine.
    """
    entries, cur = [], None
    for line in out.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "f":
            cur = {"fd": value}
            entries.append(cur)
        elif cur is not None and tag == "t":
            cur["type"] = value
        elif cur is not None and tag == "n":
            cur["name"] = value
    kept = []
    for e in entries:
        kind, name = e.get("type"), e.get("name", "")
        if kind in ("IPv4", "IPv6"):
            kept.append({"fd": e["fd"], "type": kind})
        elif kind in ("unix", "CHR") or (kind in ("REG", "DIR") and not name.startswith(
                ("/System/", "/usr/", "/Library/"))):
            kept.append({"fd": e["fd"], "type": kind, "name": anonymize(name, home)})
    return kept


def key_paths(doc, path=""):
    """The structure of a JSON document, "<path>: <type>", without any value."""
    if isinstance(doc, dict):
        return sorted(p for k, v in doc.items() for p in key_paths(v, f"{path}/{k}"))
    if isinstance(doc, list):
        return sorted({p for v in doc for p in key_paths(v, f"{path}[]")}) or [f"{path}[]"]
    return [f"{path}: {'null' if doc is None else type(doc).__name__}"]


def ps_table(out):
    """{pid: (ppid, command basename)} from `ps -axo pid=,ppid=,comm=`."""
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), os.path.basename(parts[2].strip()))
    return rows


def process_chain(rows, pid):
    """"pid ppid comm" from pid up to launchd."""
    chain = []
    while pid in rows and len(chain) < 20:
        ppid, comm = rows[pid]
        chain.append(f"{pid} {ppid} {comm}")
        if ppid == pid or ppid == 0:
            break
        pid = ppid
    return chain


def children(rows, pid):
    return [f"{p} {pid} {comm}" for p, (ppid, comm) in sorted(rows.items()) if ppid == pid]


def tree_names(root):
    """Every name below root, relative, sorted; nothing is opened."""
    found = []
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        found += [n if rel == "." else os.path.join(rel, n) for n in dirs + files]
    return sorted(found)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def agents_entry(run, job):
    """The job's entry in `claude agents --json`; the user's other sessions are dropped."""
    try:
        agents = json.loads(subprocess.run(["claude", "agents", "--json"], env=clean_env(),
                                           stdin=subprocess.DEVNULL, capture_output=True,
                                           text=True, timeout=30).stdout)
    except Exception as e:
        action(run, "claude agents failed", error=str(e))
        return None
    return [a for a in agents if isinstance(a, dict) and a.get("id") == job]


def attach_client(pid):
    """What ps and lsof show of the `claude attach` client: no env value but the allowlist."""
    home = os.path.expanduser("~")

    def run(*cmd):
        return subprocess.run(cmd, capture_output=True, text=True).stdout

    p = str(pid)
    rows = ps_table(run("ps", "-axo", "pid=,ppid=,comm="))
    tty = run("ps", "-o", "tty=,stat=", "-p", p).split()
    return {"pid": pid,
            "command": anonymize(run("ps", "-ww", "-o", "command=", "-p", p).strip(), home),
            "tty": " ".join(tty[:1]), "stat": " ".join(tty[1:]),
            "chain": process_chain(rows, pid), "children": children(rows, pid),
            "terminal": terminal_from_ps_env(run("ps", "-E", "-ww", "-o", "command=", "-p", p)),
            "open": lsof_open(run("lsof", "-nP", "-F", "ftn", "-p", p), home)}


def observe(run, what, job, client=None, journal_before=()):
    """Names (and only names or key paths) of what Claude Code exposes about a job.

    Read only, never a socket: sessions/, /tmp/cc-socks, the daemon's socket
    folder, the attach journal (new entries in full: ids, pids, flags), the
    job's folder and its roster entry, `claude agents --json`, and, while
    attached, the attach client (attach_client).
    """
    journal = os.path.join(CONFIG, "daemon", "attach-journal")
    roster = (read_json(os.path.join(CONFIG, "daemon", "roster.json")) or {}).get("workers")
    worker = roster.get(job) if isinstance(roster, dict) else None
    state = read_json(os.path.join(CONFIG, "jobs", job, "state.json"))
    data = {
        "sessions": session_names(os.path.join(CONFIG, "sessions")),
        "cc_socks": session_names("/tmp/cc-socks"),
        "daemon_dir": tree_names(f"/tmp/cc-daemon-{os.getuid()}"),
        "attach_journal": session_names(journal),
        "attach_journal_new": {n: read_json(os.path.join(journal, n))
                               for n in session_names(journal) if n not in journal_before},
        "job_dir": tree_names(os.path.join(CONFIG, "jobs", job)),
        "job_state_keys": key_paths(state) if state is not None else None,
        "job_state": {k: state.get(k) for k in ("state", "backend")} if isinstance(
            state, dict) else None,
        "roster_worker_keys": key_paths(worker) if worker is not None else None,
        "roster_worker_pids": {k: worker.get(k) for k in ("pid", "replPid")} if isinstance(
            worker, dict) else None,
        "agents": agents_entry(run, job),
        "daemon_processes": daemon_processes(),
    }
    if client is not None:
        data["attach_client"] = attach_client(client)
    action(run, what, **data)
    return data


def s24():
    """`claude attach` to a background session (#30): can an app learn its tab?

    Starts a job like S22, attaches to it in a pseudo-terminal with the
    `jobId` of its status file, records what Claude Code exposes about the
    attach client (observe), sends one prompt through it, detaches with
    Ctrl+Z (`claude attach --help`: "Ctrl+Z drops back to your shell"), then
    stops and removes the job.
    """
    run = "S24"
    action(run, "driver terminal",
           terminal={n: os.environ[n] for n in TERMINAL_NAMES if n in os.environ})
    action(run, "daemon processes before", processes=daemon_processes())
    started = now_ms()
    bg, a = None, None
    ok = "Reply with the single word ok."
    try:
        p = subprocess.run(["claude", "--bg", "--model", MODEL, ok], cwd=HERE, env=clean_env(),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        action(run, "claude --bg", status=p.returncode, stdout=p.stdout, stderr=p.stderr)
        bg = bg_job_id(p.stdout)
        if not bg:
            raise RuntimeError("claude --bg printed no id")
        start = wait_event("SessionStart", started, 90, lambda e: e.get("cwd") == HERE)
        sid = start.get("session_id")
        action(run, "saw SessionStart", session=sid)
        wait_event("Stop", started, 90, lambda e: e.get("session_id") == sid)
        action(run, "saw Stop", session=sid)
        time.sleep(3)
        files = status_files_of(os.path.join(CONFIG, "sessions"), sid)
        job = next((d.get("jobId") for _, d in files if d.get("jobId")), None)
        action(run, "status file job id", files=[
            {"file": n, "pid": d.get("pid"), "kind": d.get("kind"), "jobId": d.get("jobId")}
            for n, d in files], job_id=job, equals_printed_id=job == bg)
        if not job:
            raise RuntimeError("no jobId in the session's status file")
        journal = os.path.join(CONFIG, "daemon", "attach-journal")
        journal_before = set(session_names(journal))
        observe(run, "observe before attach", bg, journal_before=journal_before)

        a = Session(run, cmd=["claude", "attach", job])
        deadline = time.time() + 30
        while not a.out and time.time() < deadline:
            time.sleep(0.2)
        time.sleep(5)  # let it draw the conversation
        observe(run, "observe attached", bg, a.pid, journal_before)
        t = a.send(ok)
        a.wait("UserPromptSubmit", t, 60, lambda e: e.get("session_id") == sid)
        a.wait("Stop", t, 90, lambda e: e.get("session_id") == sid)
        time.sleep(3)
        observe(run, "observe attached after the turn", bg, a.pid, journal_before)

        os.write(a.fd, b"\x1a")
        action(run, "detach (ctrl+z)", pid=a.pid)
        deadline, outcome = time.time() + 15, None
        while time.time() < deadline and outcome is None:
            done, status = os.waitpid(a.pid, os.WNOHANG | os.WUNTRACED)
            if done:
                outcome = "stopped" if os.WIFSTOPPED(status) else "exited"
                action(run, f"attach client {outcome}", pid=a.pid, status=status)
            else:
                time.sleep(0.2)
        if outcome == "exited":
            LIVE.remove(a)
        else:
            action(run, "attach client still there after ctrl+z", pid=a.pid, outcome=outcome)
        time.sleep(3)
        observe(run, "observe after detach", bg, journal_before=journal_before)
    finally:
        # Leave nothing behind: the attach client, then the job in the user's daemon.
        if a is not None and a in LIVE:
            try:
                os.kill(a.pid, signal.SIGKILL)
                os.waitpid(a.pid, 0)
            except OSError:
                pass
            LIVE.remove(a)
            action(run, "attach client killed", pid=a.pid)
        jobs = [bg] if bg else s22_jobs(started, run)
        if not jobs:
            print("S24: no background job found to clean up; check `claude agents`",
                  file=sys.stderr, flush=True)
        for job in jobs:
            for cmd in ("stop", "rm"):  # each on its own: a failed stop must not skip rm
                try:
                    c = subprocess.run(["claude", cmd, job], env=clean_env(),
                                       stdin=subprocess.DEVNULL, capture_output=True,
                                       text=True, timeout=60)
                    action(run, f"claude {cmd}", id=job, status=c.returncode,
                           stdout=c.stdout, stderr=c.stderr)
                except Exception as e:
                    action(run, f"claude {cmd} failed", id=job, error=str(e))
                    print(f"S24: claude {cmd} {job} failed ({e}); check `claude agents`",
                          file=sys.stderr, flush=True)
                time.sleep(3)
        action(run, "sessions after cleanup",
               sessions=session_names(os.path.join(CONFIG, "sessions")))
        action(run, "daemon processes after cleanup", processes=daemon_processes())


def read_meta(path):
    """ppid and process chain lines of one log.sh .meta file."""
    ppid, chain, in_chain = None, [], False
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return ppid, chain
    for line in lines:
        if line.startswith("ppid="):
            ppid = int(line[5:]) if line[5:].isdigit() else None
        elif line.startswith("process chain"):
            in_chain = True
        elif in_chain and line.startswith("  "):
            chain.append(line.strip())
        else:
            in_chain = False
    return ppid, chain


def read_events(events_dir, since_ms):
    """(file, session_id, event, ppid, chain) of every event captured since since_ms."""
    events = []
    for n in sorted(os.listdir(events_dir)):
        p = os.path.join(events_dir, n)
        if not n.endswith(".json") or os.stat(p).st_mtime_ns // 1_000_000 < since_ms:
            continue
        try:
            with open(p) as f:
                ev = json.load(f)
        except (OSError, ValueError):
            continue
        ppid, chain = read_meta(p[:-5] + ".meta")
        events.append((n, ev.get("session_id"), ev.get("hook_event_name"), ppid, chain))
    return events


def pid_tally(events_dir, since_ms, modes):
    """pid_counts over the events captured since since_ms."""
    return {"since_ms": since_ms, **pid_counts(read_events(events_dir, since_ms), modes)}


def pid_counts(events, modes):
    """Per mode and hook event: how many events saw their claude pid as ppid (#28).

    events are (file, session_id, event, ppid, chain) records; modes maps each
    started claude pid to its mode. A session belongs to the pid that one of
    its events saw as ppid; an event whose session has none has mode `unknown`.
    """
    owner = {sid: ppid for _, sid, _, ppid, _ in events if ppid in modes}
    names = sorted({name for _, _, name, _, _ in events}, key=str)
    # Every known mode lists every event seen, so an event a mode never had shows as missing.
    counts = {m: {name: {"claude_pid": 0, "pid_1": 0, "other": 0, "missing": 0} for name in names}
              for m in sorted(set(modes.values()))}
    seen, outliers = set(), []
    for n, sid, name, ppid, chain in events:
        pid = owner.get(sid)
        mode = modes.get(pid, "unknown")
        c = counts.setdefault(mode, {}).setdefault(
            name, {"claude_pid": 0, "pid_1": 0, "other": 0, "missing": 0})
        kind = "claude_pid" if pid is not None and ppid == pid else "pid_1" if ppid == 1 else "other"
        c[kind] += 1
        seen.add((pid, name))
        if kind != "claude_pid":
            outliers.append({"file": n, "mode": mode, "event": name, "session_id": sid,
                             "ppid": ppid, "chain": chain})
    for pid, mode in modes.items():
        for name in names:
            counts[mode][name]["missing"] += (pid, name) not in seen
    return {"repetitions": {
        m: sum(1 for v in modes.values() if v == m) for m in sorted(set(modes.values()))},
        "counts": counts, "outliers": outliers}


def s23():
    """Does a hook started after claude exited see pid 1 (#28)?

    Hooks run async; one started after its claude process exited was
    reparented, so $PPID (the envelope's pid) is 1. Repeats `/exit` without a
    prompt and `claude -p`, then tallies the ppid of every event since.
    """
    started = now_ms()
    modes = {}
    for _ in range(20):
        try:
            s = Session("S23")
            modes[s.pid] = "interactive"
            s.ready()
            s.exit()
        except Exception as e:  # one failed repetition must not lose the tally
            action("S23", "repetition failed", error=str(e))
            for live in list(LIVE):
                live.exit_hard()
        time.sleep(3)
    for _ in range(20):
        p = subprocess.Popen(["claude", "-p", "Reply with the single word ok.", "--model", MODEL],
                             cwd=HERE, env=clean_env(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        modes[p.pid] = "headless"
        action("S23", "start claude -p", pid=p.pid)
        try:
            out, _ = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
        action("S23", "exited", pid=p.pid, status=p.returncode, stdout=out.decode(errors="replace"))
        time.sleep(3)
    time.sleep(5)
    action("S23", "pid tally", **pid_tally(EVENTS, started, modes))


# What the TUI answers to `/effort <level>` (2.1.319), as Session.out has it.
# Short markers: the TUI redraws only changed cells, so an answer drawn over an
# older one loses letters in the stream ("Effortlevelettoauto").
EFFORT_REPLIES = ((b"exceedsthecap", "capped"), (b"Failed", "failed"),
                  (b"Notapplied", "not applied"), (b"Kept", "kept"), (b"toauto", "auto"))
EFFORT_DIALOG = b"Changeeffortlevel?"  # asked once the conversation is cached
REPLY_MARK = "⎿".encode()  # starts a command's answer in the transcript
REPLY_END = ("─".encode(), "❯".encode())  # the prompt box below it


def effort_reply(out, level):
    """(kind, text) of the answer to `/effort <level>` on screen.

    The answer follows the command in the transcript; one to an earlier
    command still on screen doesn't count (so the same level twice in a row
    can't be told apart). After the confirm dialog the answer is the first one
    drawn after it, whether or not the command is drawn again. ("dialog", …)
    while only the dialog shows, (None, b"") before anything, "unknown" for an
    answer of no known kind.
    """
    cmd = b"/effort" + level.encode() + REPLY_MARK
    at, d = out.rfind(cmd), out.rfind(EFFORT_DIALOG)
    if d > at:  # the dialog's own text ("switch to auto") is never the answer
        a = out.find(REPLY_MARK, d)
        if a < 0:
            return "dialog", out[d:d + 200]
        at, cmd = a, REPLY_MARK
    elif at < 0:
        return None, b""
    text = out[at + len(cmd):at + len(cmd) + 400]
    for end in REPLY_END:
        text = text.split(end, 1)[0]
    if f"to{level}(".encode() in text:
        return "set", text
    return next((k for m, k in EFFORT_REPLIES if m in text), "unknown"), text


def set_effort(s, level, run, wait=20, now=None, sleep=None):
    """Types `/effort <level>`, logs the answer read off the screen, returns its kind.

    Confirms a "Change effort level?" dialog with its default; the answer gets
    `wait` seconds from the confirm, since it is drawn only after it.
    """
    now, sleep = now or time.time, sleep or time.sleep  # looked up per call: s25's tests fake the clock
    s.clear()
    s.send(f"/effort {level}")
    deadline, confirmed = now() + wait, False
    while True:
        kind, text = effort_reply(s.out, level)
        if kind == "dialog" and not confirmed:
            s.keys("change effort level dialog: default", ENTER)
            deadline, confirmed = now() + wait, True
        elif kind not in (None, "dialog"):
            break
        if now() > deadline:
            raise TimeoutError(f"/effort {level}: no answer on screen: {s.out[-300:]!r}")
        sleep(0.2)
    sleep(1)  # let the line finish drawing
    kind, text = effort_reply(s.out, level)
    action(run, "effort answer", level=level, kind=kind, dialog=confirmed,
           screen=text.decode(errors="replace"))
    if kind not in ("set", "capped", "auto"):
        raise RuntimeError(f"/effort {level}: {kind}")
    return kind


# What the TUI draws while typing into it would answer a dialog or end up in a
# running turn (2.1.316, 2.1.319). Session.out is a stream, not a screen: the
# caller clears it once the TUI is idle, so any marker since then is current.
# Enter in a permission dialog picks its default "Yes" and runs the tool.
DIALOG_MARKERS = (b"Entertoconfirm", b"Esctocancel", "❯1.".encode(), b"Doyouwanttoproceed?",
                  EFFORT_DIALOG, EXIT_DIALOG, *DIALOGS)
# The spinner ("Roosting…(0s·↓34tokens)", not a collapsed "…(+3morelines)"), background agents.
TURN_MARKERS = re.compile("…\\((\\d|running)|backgroundagents?tofinish".encode())


def typing_blocker(out):
    """Why typing into the TUI now is unsafe ("dialog open", "turn running"), else None.

    out is what the TUI drew since the driver last saw it idle at its prompt.
    """
    if any(m in out for m in DIALOG_MARKERS):
        return "dialog open"
    if TURN_MARKERS.search(out):
        return "turn running"
    return None


SONNET = "claude-sonnet-5-5"  # the model S25 runs on, its key in `modelSettings`


def sonnet_model_settings(settings):
    """The sonnet entry of `modelSettings` in ~/.claude/settings.json, nothing else of it."""
    return ((settings or {}).get("modelSettings") or {}).get(SONNET)


def restore_level(entry):
    """The `/effort` argument that puts back the saved sonnet entry: its level, else auto."""
    return (entry or {}).get("effortLevel") or "auto"


def s25():
    """Effort levels (#37): which hooks carry `effort`, and which level.

    Sonnet, since haiku sends no `effort`. One Bash call at the default level,
    then `/effort` through every level with one Bash call each, a failing Bash
    call, and still at `max` (this session only; the saved default is then
    `xhigh`) two Agent calls, one with its own `effort` and one inheriting, so
    an inheriting subagent shows whether it gets the session's level or the
    saved one. Every /effort answer is read off the screen and logged; a
    "Change effort level?" dialog is confirmed with its default, anything else
    unexpected fails the run. `/effort` saves the level for sonnet in
    ~/.claude/settings.json (`modelSettings`), so the run ends by setting the
    sonnet entry it found back (its level, or `/effort auto`, which clears it).
    That entry, and nothing else of the file, is logged before, ahead of the
    Agent calls and after. Nothing is typed while the screen shows a dialog or
    a running turn, nor into a prompt box whose last input the TUI wasn't seen
    to take: the cleanup after a failure is skipped then, and logged. A
    session that starts on another model than SONNET stops before any input.
    """
    levels = ("low", "medium", "high", "xhigh", "max")
    fail = "ls captures/nonexistent-dir"
    subs = ("echo sub-high", "echo sub-inherit")
    bash = ["echo default", *(f"echo {lv}" for lv in levels), fail, *subs]
    settings = os.path.join(CONFIG, "settings.json")

    def sonnet_settings(what):
        entry = sonnet_model_settings(read_json(settings))
        action("S25", f"settings sonnet entry {what}", modelSettings={SONNET: entry})
        return entry

    def guard(what):
        # s.out holds what the TUI drew since it was last seen idle (settled()).
        # The calls in turn, effort, before the Agent prompt and /exit are
        # deliberate backups behind settled() and the first-prompt guard: keep them.
        blocker = typing_blocker(s.out)
        if blocker:
            raise RuntimeError(f"{what}: {blocker} on screen, not typing: {s.out[-300:]!r}")

    unconfirmed = None  # input typed and not yet seen through to an idle prompt

    def settled():
        # s.out holds what the TUI drew since the turn or command ended: a dialog
        # drawn then must stop the run, not be dropped unseen.
        nonlocal unconfirmed
        guard("next keystroke")
        s.clear()
        unconfirmed = None

    def turn(text):
        nonlocal unconfirmed
        guard(f"prompt {text!r}")
        unconfirmed = text
        t = s.send(text)
        n = s.wait("UserPromptSubmit", t, 60, lambda e: e.get("prompt") == text)
        s.wait("Stop", t, 120, lambda e: e.get("prompt_id") == n.get("prompt_id"))
        # out is cleared once the poller sees the Stop, so text drawn between the
        # Stop and the clear goes unchecked. Accepted: before the Stop, the turn's
        # own spinner can't be told apart from a running turn; settled() checks
        # what is drawn after the clear.
        s.clear()  # the turn's own spinner is over; only what follows its Stop counts
        time.sleep(3)
        settled()
        return t

    def run_bash(cmd):
        return turn(f"Run exactly this Bash command once and nothing else: {cmd}")

    def effort(level):
        nonlocal unconfirmed
        guard(f"/effort {level}")
        unconfirmed = f"/effort {level}"
        set_effort(s, level, "S25")
        # set_effort confirmed its own dialog; what counts starts at the answer after it.
        def answer(out):
            d = out.rfind(EFFORT_DIALOG)
            return out.find(REPLY_MARK, d) if d >= 0 else -1
        s.keep_from(answer)
        settled()

    saved = sonnet_settings("before")
    s = Session("S25", ["--permission-mode", "default", "--allowedTools", "Agent",
                        *(f"Bash({c})" for c in bash)], model="sonnet",
                env={"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1"})
    start, answered = s.ready()
    if answered is not None:  # its leftovers ("Entertoconfirm", "❯1.") are no dialog open;
        s.keep_since(answered)  # what was drawn after its Enter still counts
    # SONNET names the `modelSettings` entry to put back; on another model the
    # restore would clear the user's saved level, so stop before any /effort.
    if start.get("model") != SONNET:
        action("S25", "unexpected model", model=start.get("model"), expected=SONNET)
        raise RuntimeError(f"S25 runs on {start.get('model')!r}, not {SONNET}: no /effort typed")
    try:
        guard("first prompt")  # a dialog ready() doesn't know: never type into it
        run_bash("echo default")
        for lv in levels:
            effort(lv)
            run_bash(f"echo {lv}")
        run_bash(fail)
        sonnet_settings("before the Agent calls")  # the saved default, against the session's max
        text = ("Call the Agent tool twice in one message, both with subagent_type "
                "general-purpose and no model parameter. First call: effort high, prompt "
                f"'Run exactly this Bash command once and nothing else: {subs[0]}'. Second "
                f"call: no effort parameter, prompt 'Run exactly this Bash command once and "
                f"nothing else: {subs[1]}'. Then reply with both results.")
        guard("Agent prompt")
        unconfirmed = text
        t = s.send(text)
        done = []
        while len(done) < 2:
            e = s.wait("SubagentStop", t, 240, lambda e: e.get("agent_type") == "general-purpose"
                       and e.get("agent_id") not in done)
            done.append(e.get("agent_id"))
        # 2.1.319 runs them in the background: each result comes back in a
        # <task-notification> turn of its own; wait for both turns' Stop.
        for agent in done:
            n = s.wait("UserPromptSubmit", t, 120, lambda e, a=agent: str(
                e.get("prompt", "")).startswith("<task-notification>") and a in e["prompt"])
            s.wait("Stop", t, 120, lambda e, n=n: e.get("prompt_id") == n.get("prompt_id"))
        # As in turn(): cleared once the poller sees the last Stop, so text drawn
        # between that Stop and the clear goes unchecked; settled() checks what follows.
        s.clear()  # the "Waiting for 2 background agents" turn is over
        time.sleep(5)
        settled()
    finally:
        # Also after a failure: put back the user's saved sonnet level, unless
        # the screen may answer a dialog (Enter picks "Yes" in a permission
        # prompt), a turn is still running, or the last input may still sit in
        # the prompt box (no spinner then, so typing_blocker can't tell).
        level, blocker = restore_level(saved), typing_blocker(s.out)
        if not blocker and unconfirmed is not None:
            blocker = "prompt not confirmed"
        if s in LIVE and blocker:
            action("S25", "effort restore skipped", level=level, reason=blocker)
        elif s in LIVE:
            try:
                effort(level)
            except Exception as e:
                action("S25", "effort restore failed", level=level, error=str(e))
    guard("/exit")
    s.exit()
    sonnet_settings("after")


RUNS = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6, "S7": s7,
        "S8": s8, "S9": s9, "S10": s10, "S11": s11, "S12": s12, "S13": s13,
        "S14": s14, "S15": s15, "S16": s16,
        "S17": s17, "S18": s18, "S19": s19, "S20": s20, "S21": s21, "S22": s22,
        "S23": s23, "S24": s24, "S25": s25}


def main():
    wanted = sys.argv[1:] or list(RUNS)
    for d in (EVENTS, SESSIONS_OUT, TTY):
        os.makedirs(d, exist_ok=True)
    watcher = subprocess.Popen([os.path.join(HERE, "watch-sessions.py")],
                               stdout=subprocess.DEVNULL)
    time.sleep(1)
    failed = []
    try:
        for name in wanted:
            try:
                RUNS[name]()
            except Exception as e:  # keep going; the tty log shows what happened
                action(name, "failed", error=str(e))
                failed.append(name)
                for live in list(LIVE):
                    live.exit_hard()
            time.sleep(3)
    finally:
        time.sleep(5)
        watcher.terminate()
        watcher.wait()
        subprocess.run([os.path.join(HERE, "collect.sh")], cwd=HERE)
    if failed:
        print("failed: " + " ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
