#!/usr/bin/env python3
"""Plays the runs S1-S18 of README.md without a human (#58).

Starts watch-sessions.py, then drives interactive `claude` sessions in a
pseudo-terminal: types prompts, presses Enter, Esc and Ctrl-C, and waits for
the hook events in captures/events/ (never for the status file under test).
Every action goes to captures/sessions/actions.jsonl with wall-clock ms, the
terminal output of each run to captures/tty/<run>.log. Runs collect.sh at
the end. Uses haiku; costs a few cents.

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
    def __init__(self, run, args=(), model=MODEL, env=None):
        self.run = run
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(HERE)
            os.execvpe("claude", ["claude", "--model", model, *args], {**clean_env(), **(env or {})})
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self.log = open(os.path.join(TTY, f"{run}.log"), "ab")
        self.out = b""
        LIVE.append(self)
        threading.Thread(target=self._drain, daemon=True).start()
        self.started = now_ms()
        action(run, "start", pid=self.pid, model=model, args=list(args))

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
            self.out = (self.out + ANSI.sub(b"", data))[-20000:]

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
        deadline = time.time() + 60
        while True:
            try:
                self.wait("SessionStart", self.started, 1)
                break
            except TimeoutError:
                if time.time() > deadline:
                    raise
            for d in DIALOGS:
                if d in self.out:
                    self.out = self.out.replace(d, b"")
                    self.keys(f"dialog {d.decode()}: default", ENTER)
        time.sleep(3)

    def exit(self):
        self.out = b""
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
    s.out = b""
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


RUNS = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6, "S7": s7,
        "S8": s8, "S9": s9, "S10": s10, "S11": s11, "S12": s12, "S13": s13,
        "S14": s14, "S15": s15, "S16": s16,
        "S17": s17, "S18": s18}


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
