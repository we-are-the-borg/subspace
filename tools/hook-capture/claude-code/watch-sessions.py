#!/usr/bin/env python3
"""Records Claude Code's session status files (#58) next to the hook capture.

Polls <config dir>/sessions/ (CLAUDE_CONFIG_DIR, else ~/.claude) and writes
to captures/sessions/ (or $WATCH_SESSIONS_OUT):

- NNNNNN-<pid>.json: the file's bytes, on every change of content or inode
- log.jsonl: one line per observation (created, changed, deleted, other)
  with wall-clock ms, inode, mtime_ns and size, so the snapshots can be
  interleaved with the hook events (whose files carry an mtime too)

Only files whose cwd lies inside this directory are recorded; once a pid is
recorded it stays recorded, even if its file switches session or cwd. Other
names in sessions/ (temp files of an atomic write, say) are logged by name
only. *.key files are never read. Stop with Ctrl-C (or SIGTERM).
"""
import json
import os
import signal
import sys
import time

HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
SESSIONS = os.path.join(CONFIG, "sessions")
OUT = os.environ.get("WATCH_SESSIONS_OUT") or os.path.join(HERE, "captures", "sessions")
INTERVAL = 0.05


def now_ms():
    return time.time_ns() // 1_000_000


def inside(cwd):
    return isinstance(cwd, str) and (cwd == HERE or cwd.startswith(HERE + os.sep))


def main():
    os.makedirs(OUT, exist_ok=True)
    seq = len([n for n in os.listdir(OUT) if n.endswith(".json")])
    log = open(os.path.join(OUT, "log.jsonl"), "a", buffering=1)
    tracked = {}  # pid -> (inode, mtime_ns, size, bytes)
    others = set()

    def record(entry):
        entry = {"ms": now_ms(), **entry}
        log.write(json.dumps(entry) + "\n")
        print(json.dumps(entry), flush=True)

    print(f"watching {SESSIONS} for cwd inside {HERE}", file=sys.stderr)
    while True:
        try:
            names = set(os.listdir(SESSIONS))
        except FileNotFoundError:
            names = set()

        for name in sorted(names - others):
            if not name.endswith((".json", ".key")):
                record({"event": "other", "file": name})
        others = {n for n in names if not n.endswith((".json", ".key"))}

        for name in sorted(n for n in names if n.endswith(".json")):
            pid = name[: -len(".json")]
            path = os.path.join(SESSIONS, name)
            try:
                with open(path, "rb") as f:
                    st = os.fstat(f.fileno())
                    data = f.read()
            except OSError:
                continue
            state = (st.st_ino, st.st_mtime_ns, st.st_size, data)
            old = tracked.get(pid)
            if old == state:
                continue
            if old is None:
                try:
                    cwd = json.loads(data).get("cwd")
                except (ValueError, AttributeError):
                    cwd = None
                if not inside(cwd):
                    continue
            tracked[pid] = state
            seq += 1
            snap = f"{seq:06d}-{pid}.json"
            with open(os.path.join(OUT, snap), "wb") as f:
                f.write(data)
            record({
                "event": "created" if old is None else "changed",
                "pid": pid,
                "snapshot": snap,
                "inode": st.st_ino,
                "inode_changed": old is not None and old[0] != st.st_ino,
                "mtime_ns": st.st_mtime_ns,
                "size": st.st_size,
            })

        for pid in [p for p in tracked if f"{p}.json" not in names]:
            del tracked[pid]
            record({"event": "deleted", "pid": pid})

        time.sleep(INTERVAL)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        main()
    except KeyboardInterrupt:
        pass
