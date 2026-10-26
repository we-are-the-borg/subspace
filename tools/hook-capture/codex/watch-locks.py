#!/usr/bin/env python3
"""Records Codex's thread writer lock files (#5) next to the hook capture.

Polls $CODEX_HOME/thread-writer-locks/ (CODEX_HOME, else ~/.codex) and writes
captures/locks/log.jsonl (or $WATCH_LOCKS_OUT), one line per observation with
wall-clock ms, so it can be interleaved with the hook events:

- present: a lock file that existed when the watcher started (baseline)
- created / deleted: a lock file appeared or vanished (with inode, mtime_ns)
- holder: the process holding the file open changed (pid and comm from
  `lsof`, null when nobody has it open, e.g. after a crash)
- fsevent: what FSEvents reported for the folder (fsevents.swift, macOS
  only), to check that apps watching the folder see every removal
- other: any other name in the folder, logged once

Read only: never creates, locks or deletes anything there, and never probes
the locks with flock (that could block a real writer). Stop with Ctrl-C (or
SIGTERM).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
LOCKS = os.path.join(CODEX_HOME, "thread-writer-locks")
OUT = os.environ.get("WATCH_LOCKS_OUT") or os.path.join(HERE, "captures", "locks")
INTERVAL = 0.05
HOLDER_INTERVAL = 1.0


def now_ms():
    return time.time_ns() // 1_000_000


def holders(paths):
    """Maps each path that a process has open to {"pid", "comm"}."""
    if not paths:
        return {}
    try:
        out = subprocess.run(
            ["lsof", "-n", "-F", "pcn", "--", *paths],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found, pid, comm = {}, None, None
    for line in out.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid, comm = int(value), None
        elif tag == "c":
            comm = value
        elif tag == "n":
            found[value] = {"pid": pid, "comm": comm}
    return found


def main():
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, "log.jsonl"), "a", buffering=1)
    lock = threading.Lock()

    def record(entry):
        entry = {"ms": now_ms(), **entry}
        line = json.dumps(entry)
        with lock:
            log.write(line + "\n")
            print(line, flush=True)

    fsevents = None
    swift = shutil.which("swift")
    if swift and os.path.isdir(LOCKS):
        fsevents = subprocess.Popen(
            [swift, os.path.join(HERE, "fsevents.swift"), LOCKS],
            stdout=subprocess.PIPE, text=True,
        )

        def pump():
            for line in fsevents.stdout:
                try:
                    record({"event": "fsevent", **json.loads(line)})
                except ValueError:
                    record({"event": "fsevent", "raw": line.rstrip("\n")})

        threading.Thread(target=pump, daemon=True).start()
    else:
        print("no FSEvents check (swift missing or folder absent)", file=sys.stderr)

    print(f"watching {LOCKS}", file=sys.stderr)
    tracked = {}  # file name -> (inode, mtime_ns); written by the main loop only

    def watch_holders():
        # lsof takes long enough to delay the polling, so it runs on its own.
        held = {}  # file name -> holder dict or None
        while True:
            paths = {os.path.join(LOCKS, n): n for n in list(tracked)}
            found = holders(list(paths))
            for name in [n for n in held if n not in paths.values()]:
                del held[name]
            for path, name in paths.items():
                holder = found.get(path)
                if name not in tracked:
                    continue
                if name not in held or held[name] != holder:
                    held[name] = holder
                    record({
                        "event": "holder",
                        "thread": name[: -len(".lock")],
                        "holder": holder,
                    })
            time.sleep(HOLDER_INTERVAL)

    others = set()
    first = True
    try:
        while True:
            try:
                names = set(os.listdir(LOCKS))
            except FileNotFoundError:
                names = set()

            for name in sorted(names - others):
                if not name.endswith(".lock") or name.startswith("."):
                    record({"event": "other", "file": name})
            others = {n for n in names if not n.endswith(".lock") or n.startswith(".")}

            for name in sorted(names - others - tracked.keys()):
                try:
                    st = os.stat(os.path.join(LOCKS, name))
                except OSError:
                    continue
                tracked[name] = (st.st_ino, st.st_mtime_ns)
                record({
                    "event": "present" if first else "created",
                    "thread": name[: -len(".lock")],
                    "inode": st.st_ino,
                    "mtime_ns": st.st_mtime_ns,
                    "size": st.st_size,
                })

            for name in sorted(tracked.keys() - names):
                del tracked[name]
                record({"event": "deleted", "thread": name[: -len(".lock")]})

            if first:
                threading.Thread(target=watch_holders, daemon=True).start()
            first = False
            time.sleep(INTERVAL)
    finally:
        if fsevents:
            fsevents.terminate()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        main()
    except KeyboardInterrupt:
        pass
