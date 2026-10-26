#!/usr/bin/env python3
"""Plays the writer lock runs A-G of README.md section 7 without a human (#5).

Starts watch-locks.py unless one is already running, then drives `codex` in a
pseudo-terminal from the repository root (trusted, and outside this capture
project, whose hooks are trusted per path): types prompts, `/exit`, closes the
terminal or kills the process, and waits for the hook events of the installed
subspace plugin in $CODEX_HOME/plugins/data/subspace-subspace/events/ (never
for the lock files under test). Every action goes to
captures/locks/actions.jsonl with wall-clock ms, the terminal output of each
run to captures/tty/<run>.log. Run H (ChatGPT app) stays manual.

Usage: ./drive-lock-runs.py [A B …]   (default: A-G)
"""
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
CAPTURES = os.path.join(HERE, "captures")
LOCKS_OUT = os.path.join(CAPTURES, "locks")
TTY = os.path.join(CAPTURES, "tty")
RUNS_OUT = os.path.join(CAPTURES, "runs")
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
EVENTS = os.path.join(CODEX_HOME, "plugins", "data", "subspace-subspace", "events")
UNLOAD_WAIT = 120  # the default unload delay of an idle thread is 60 s
ENTER = "\r"
ANSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]")
LIVE = []  # sessions to kill if a run fails
SESSIONS = {}  # run -> root session_id


def now_ms():
    return time.time_ns() // 1_000_000


def clean_env():
    """This script may run inside another agent; the runs must not notice."""
    drop = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_PID", "CLAUDE_JOB_DIR",
            "CLAUDE_EFFORT", "AI_AGENT", "CODEX_")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def action(run, what, **extra):
    entry = {"ms": now_ms(), "run": run, "action": what, **extra}
    with open(os.path.join(LOCKS_OUT, "actions.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def wait_event(name, since_ms, timeout, pred=None):
    """The first hook event `name` whose file appeared after since_ms."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for root, _, files in os.walk(EVENTS):
            for n in sorted(files):
                if not n.endswith(".json"):
                    continue
                p = os.path.join(root, n)
                try:
                    if os.stat(p).st_mtime_ns // 1_000_000 < since_ms:
                        continue
                    with open(p) as f:
                        ev = json.load(f)["payload"]
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                if ev.get("hook_event_name") == name and (pred is None or pred(ev)):
                    return ev
        time.sleep(0.2)
    raise TimeoutError(f"no {name} within {timeout}s")


def root(ev):
    return not ev.get("agent_id")


class Session:
    def __init__(self, run, args):
        self.run = run
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(REPO)
            os.execvpe("codex", ["codex", *args], clean_env())
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self.log = open(os.path.join(TTY, f"{run}.log"), "ab")
        self.out = b""
        self.last_output = time.time()
        LIVE.append(self)
        self.stop = threading.Event()
        self.drain = threading.Thread(target=self._drain, daemon=True)
        self.drain.start()
        action(run, "start", pid=self.pid, args=list(args))

    def _drain(self):
        # Never block in read: on macOS close() waits for a read on the same fd.
        while not self.stop.is_set():
            if not select.select([self.fd], [], [], 0.2)[0]:
                continue
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                return
            if not data:
                return
            self.log.write(data)
            self.log.flush()
            self.out = (self.out + ANSI.sub(b"", data))[-20000:]
            self.last_output = time.time()

    def settle(self, quiet=3, timeout=60):
        """Waits until the terminal has been quiet for `quiet` seconds."""
        deadline = time.time() + timeout
        time.sleep(quiet)
        while time.time() - self.last_output < quiet and time.time() < deadline:
            time.sleep(0.2)

    def type(self, text):
        os.write(self.fd, text.encode())
        time.sleep(0.7)
        os.write(self.fd, ENTER.encode())
        action(self.run, "send", pid=self.pid, text=text)
        return now_ms() - 1000

    def prompt(self, text, timeout=300):
        ev = wait_event("Stop", self.type(text), timeout, root)
        SESSIONS.setdefault(self.run, ev["session_id"])
        action(self.run, "saw Stop", pid=self.pid, session_id=ev["session_id"])
        return ev

    def exit(self):
        self.type("/exit")
        self.reap(30)

    def close_terminal(self):
        self.stop.set()
        self.drain.join()
        os.close(self.fd)
        action(self.run, "closed terminal", pid=self.pid)
        self.reap(30)

    def kill(self, sig):
        os.kill(self.pid, sig)
        action(self.run, f"kill -{signal.Signals(sig).name}", pid=self.pid)
        self.reap(10)

    def reap(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                LIVE.remove(self)
                action(self.run, "exited", pid=self.pid, status=status)
                return
            time.sleep(0.1)
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        LIVE.remove(self)
        action(self.run, "killed after timeout", pid=self.pid)


def pause(run, seconds):
    action(run, f"wait {seconds}s")
    time.sleep(seconds)


def run_a():
    s = Session("A", ["-s", "read-only"])
    s.settle()
    s.type("/status")
    s.settle()
    s.prompt("Reply with lock-a.")
    s.exit()
    pause("A", UNLOAD_WAIT)


def run_b():
    s = Session("B", ["--no-daemon", "-s", "read-only"])
    s.settle()
    s.prompt("Reply with lock-b.")
    s.exit()
    pause("B", 10)


def run_c():
    s = Session("C", ["resume", SESSIONS["A"], "-s", "read-only"])
    s.settle()
    pause("C", 10)  # does the lock come back before the first prompt?
    s.prompt("Reply with lock-c.")
    s.exit()
    pause("C", UNLOAD_WAIT)


def run_d():
    s = Session("D", ["-s", "read-only"])
    s.settle()
    s.prompt("Start one subagent that replies with lock-d-child and wait for "
             "it, then reply with lock-d. Do not run any commands.", timeout=600)
    s.exit()
    pause("D", UNLOAD_WAIT)


def run_e():
    s = Session("E", ["-s", "read-only"])
    s.settle()
    s.prompt("Reply with lock-e.")
    s.close_terminal()
    pause("E", UNLOAD_WAIT)


def run_f():
    s = Session("F", ["--no-daemon", "-s", "read-only"])
    s.settle()
    s.prompt("Reply with lock-f.")
    s.kill(signal.SIGKILL)
    pause("F", 10)
    s = Session("F2", ["--no-daemon", "-s", "read-only"])
    s.settle()
    pause("F2", 5)
    s.prompt("Reply with lock-f2.")
    s.exit()
    pause("F2", 10)


def run_g():
    for run, extra in (("G", []), ("G2", ["--ephemeral"])):
        action(run, "start exec", args=extra)
        with open(os.path.join(RUNS_OUT, f"locks-{run}.jsonl"), "w") as out:
            done = subprocess.run(
                ["codex", "exec", *extra, "-s", "read-only", "--json",
                 f"Reply with lock-{run.lower()}."],
                cwd=REPO, env=clean_env(), stdin=subprocess.DEVNULL,
                stdout=out, stderr=subprocess.STDOUT, timeout=300,
            )
        action(run, "exec exited", status=done.returncode)
        pause(run, 10)


RUNS = {"A": run_a, "B": run_b, "C": run_c, "D": run_d, "E": run_e,
        "F": run_f, "G": run_g}


def main():
    wanted = sys.argv[1:] or list(RUNS)
    for d in (LOCKS_OUT, TTY, RUNS_OUT):
        os.makedirs(d, exist_ok=True)
    watcher = None
    if subprocess.run(["pgrep", "-f", "watch-locks.py"],
                      stdout=subprocess.DEVNULL).returncode != 0:
        watcher = subprocess.Popen([os.path.join(HERE, "watch-locks.py")],
                                   stdout=subprocess.DEVNULL)
        time.sleep(3)
    with open(os.path.join(RUNS_OUT, "version-locks.txt"), "w") as f:
        subprocess.run(["codex", "--version"], stdout=f, env=clean_env())
    failed = []
    try:
        for name in wanted:
            try:
                RUNS[name]()
            except Exception as e:  # keep going; the tty log shows what happened
                action(name, "failed", error=str(e))
                failed.append(name)
                for live in list(LIVE):
                    live.kill(signal.SIGTERM)
    finally:
        if watcher:
            watcher.terminate()
            watcher.wait()
        print(json.dumps(SESSIONS), flush=True)
    if failed:
        print("failed: " + " ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
