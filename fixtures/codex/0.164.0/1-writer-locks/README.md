# Writer lock files

When `$CODEX_HOME/thread-writer-locks/<thread-id>.lock` appears and disappears, observed for contract §14 (#5). Runs A–G were played in a pseudo-terminal by `tools/hook-capture/codex/drive-lock-runs.py` from the repository root; run H was done by hand in the ChatGPT desktop app. `watch-locks.py` polled the folder every 50 ms, read the holder with `lsof` once a second and logged what FSEvents reported.

`timeline.jsonl` merges both logs in wall-clock order (`ms`):

- `{"run", "action", …}`: what the driver did (`start` with the CLI arguments, `send` with the typed text, `saw Stop` with the root `session_id` from the hook event, `exited`, `closed terminal`, `kill -SIGKILL`, `wait`). `manual: …` entries were written by hand: run E's first attempt (below) and run H's notes, which have second precision.
- `{"event", "thread", …}` from the watcher: `created` and `deleted` (detected by polling), `holder` (`pid`, `comm`; null when no process has the file open) and `fsevent` (`file`, `flags`, `id`).

Only the runs' threads are kept, plus the two older ChatGPT app chats whose locks went away when the app quit. Thread IDs, process IDs and timestamps are unchanged; nothing else in the logs is personal.

## Threads

Holder `76118` is the managed app-server daemon, `79009` the ChatGPT app's app-server; the others are processes of the run.

| Run | Thread (lock file name) | Role |
|---|---|---|
| A, C | `01a17900-d3f8-71d1-a99a-21ef53523bde` | root session (A; C resumed it) |
| A | `01a17900-d45c-7b70-ae15-f7e303cfa603` | helper |
| B | `01a17900-46a3-7de3-81be-56c8429da567` | root session |
| B | `01a17900-46f7-7763-b801-e83973ee0690` | helper |
| C | `01a17902-e556-72f2-8c8c-d735d6660434` | helper |
| D | `01a17905-0996-7ec2-aa60-28e2996c7d1e` | root session |
| D | `01a17905-09e8-7603-be8e-26c2985cce20` | helper |
| D | `01a17905-3104-7721-b1e0-897fdacd2bd5` | child thread (`agent_id` of `SubagentStart`) |
| D | `01a17905-31cf-7b80-abeb-b0e2062c0cd9` | helper of the child |
| E (1st) | `01a17907-2d44-7a42-b71e-578795dc2cc5` | root session |
| E (1st) | `01a17907-2da0-7280-a6cc-3fc58ccf63fc` | helper |
| E | `01a1791c-0a1c-7513-9279-149254481caa` | root session |
| E | `01a1791c-0a86-7660-a95c-9ea1929b7dba` | helper |
| F | `01a1791e-05d7-7d02-b380-8198ced021c9` | root session |
| F | `01a1791e-0624-7940-8de4-d8feb0018597` | helper |
| F2 | `01a1791e-4e73-76e2-83b6-e6a725ae02e0` | root session |
| F2 | `01a1791e-4ead-71c2-9d51-9d2b6650a159` | helper |
| G | `01a1791e-b101-7490-8f34-07c4d810ef77` | root session (`codex exec`) |
| G | `01a1791e-b142-76c1-ab53-90f55825f400` | helper |
| H | `01a17901-71f6-7ce1-81e8-e7ee1381dd15` | root session (ChatGPT app chat) |
| H | `01a17901-72a4-7ca0-85c9-b98d7b6fa514` | helper |
| H | `01a16a75-7780-71b1-8db9-cb482635386b`, `01a16a7a-360b-7e43-aec1-9938a2ae87e7` | older ChatGPT app chats (2026-10-23), loaded until the app quit |

A root session's lock file name is the hooks' `session_id` in every run (A–H). A **helper** is a second thread created 50–170 ms after each root or child thread, held by the same process and removed with it. It has no hook events and no rollout under `sessions/`; what it does is unknown.

## Runs and results

| Run | What was done | Lock of the root session |
|---|---|---|
| A | `codex -s read-only` (daemon; `/status`), one prompt, `/exit` 17:17:54.262 | stayed; still loaded when C resumed it 2 min later |
| B | `codex --no-daemon -s read-only`, one prompt, `/exit` 17:17:12.524 | removed 17:17:12.538 (FSEvents), before the process ended |
| C | `codex resume <A> -s read-only`, waited 10 s, one prompt, `/exit` 17:20:14.623 | at start 17:19:55.314 A's locks deleted and 52 ms later re-created (before any prompt); removed 17:50:14.656, **1800.0 s after `/exit`** |
| D | daemon, prompt that spawns one subagent, `/exit` 17:22:34.860 | removed 17:52:34.927 (1800.1 s); the **child's lock and its helper's were not removed**: still present at the end of the watch (18:17:32) and after it |
| E | daemon, one prompt, terminal closed (pty master closed, `codex` got SIGHUP) 17:47:31.957 | removed 18:17:32.011 (1800.1 s) |
| E (1st) | same, the turn took 2.5 min; the driver hung on closing the terminal and was killed, closing it 17:46:49.528 | removed 18:16:49.600 (1800.1 s) |
| F | `--no-daemon`, one prompt, `SIGKILL` 17:49:40.693 | file stayed; holder null from the next `lsof` (17:49:41.397) |
| F2 | `--no-daemon` again 17:49:50.813 | F's stale locks removed 17:49:51.769, with F2's first lock (stale cleanup on the first acquire of a process); F2's own lock removed 5 ms after `/exit` |
| G | `codex exec -s read-only` | created 92 ms after start, removed 17:50:21.717, before the process exited (17:50:23.769) |
| G2 | `codex exec --ephemeral -s read-only` | no lock file (hook events with this `session_id` exist) |
| H | ChatGPT app: new chat 17:18:20, prompt, chat archived; app quit (Cmd-Q, noted 17:19:43) | chat's locks removed 17:18:51.244, after archiving (archive time not noted); older chats' locks removed 17:19:39 when the app quit |

FSEvents (file events, no latency) reported every creation and removal. Within one event the flags accumulate: a removal often came as `["created", "removed", "xattr_mod", "is_file"]`, so a consumer checks whether the file exists rather than reading the flags.

## Codex sources

- [`writer_lock.rs`](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/rollout/src/writer_lock.rs) (identical since at least 0.158.0): path, `flock` on the open file, removal when the writer is dropped, stale cleanup on a process's first acquire.
- [`thread_lifecycle.rs`](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/app-server/src/request_processors/thread_lifecycle.rs): an app-server unloads a thread once it has had no subscribers and no active turn for `thread_unload_delay`.
- [`config/mod.rs`](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/core/src/config/mod.rs): `thread_unload_delay_secs`, default 1800 since 0.163.0 (60 in 0.160.0–0.162.1). Not observed with 60 s.
