# Fixtures: Claude Code 2.1.287

Real hook payloads and session status files, recorded on 2026-10-02 on macOS with `tools/hook-capture/claude-code/drive-session-runs.py`: the driver plays each run in a pseudo-terminal, `watch-sessions.py` snapshots `~/.claude/sessions/<pid>.json` every 50 ms. Both apps test their combination of hook events and status file against these runs.

## Layout

```
<run>/
├── events/NNN-<hook_event_name>.json   # raw payload, byte for byte
├── expected/NNN-<hook_event_name>.json # model/claude-code.json applied to it (docs/model.md §7)
├── status/NNN-status.json              # the session status file as read, byte for byte
├── status-expected/NNN-status.json     # model/claude-code-session.json applied to it (docs/model.md §12)
└── timeline.jsonl                      # everything in observed order, see below
```

`NNN` is one sequence per run over hook events and status snapshots together, in observed order: hook events by file mtime (async hooks are written slightly after the event), snapshots by the time the watcher read them. Status snapshots carry `statusUpdatedAt`, which is when Claude Code changed the status (10–330 ms earlier).

`timeline.jsonl` has one line per entry with wall-clock `ms`, and one of:
- `file`: the event or snapshot (`n` = `NNN`); snapshots add `inode_changed` (true: the file was replaced by a rename, false: written in place)
- `action`: what the driver did (`send: <text>`, `press esc mid-turn`, `kill -9`, …). Esc and Ctrl-C leave no hook event, so this is the only record of them
- `file_deleted`: the status file disappeared

Payloads and status files are unchanged, anonymized as described in [`../../README.md`](../../README.md#anonymization). Transcripts are not included.

## Runs

| Run | What happened | Status sequence |
|---|---|---|
| `1-idle-exit` | `hi`, answer, `/exit` | – idle busy idle busy, deleted |
| `2-interrupt-mid-turn` | long story, Esc while streaming; again, Ctrl-C while streaming; `/exit` | – idle busy **idle** busy **idle**, deleted; no `Stop` after either interrupt |
| `3-interrupt-mid-tool` | `sleep 20` allowed by `--allowedTools`, Esc during the sleep | – idle busy **idle**; no `PostToolUse`, no `Stop` |
| `4-waiting-permission-question` | `touch` needing permission, approved after 15 s; again, rejected after 15 s; `AskUserQuestion`, answered after 15 s | – idle busy **waiting** (`permission prompt`) busy idle busy **waiting** idle busy **waiting** (`input needed`) busy idle |
| `5-bang-shell` | `! sleep 10` in bash mode | – idle busy idle busy, deleted: `busy`, not `shell` |
| `6-background-subagents` | Sonnet; two `Agent` calls, both launched async; results handed back as `<agent-message …>` | – idle busy … busy idle: **busy across two `Stop`s** until the last hand-back turn ended |
| `6a-background-shell-exit-dialog-killed` | Haiku; one `Agent` call (async, result as `<task-notification>`) and a background shell; `/exit` opened "Background work is running"; the driver killed the process after 30 s | – idle busy busy **shell** **waiting** (`dialog open`); file left behind, deleted when run 7 started |
| `7-continue` | `claude --continue` (resumes run 6a's session), `hi`, `/exit` | – – idle busy idle: the first snapshot carries a fresh `sessionId`, the second the resumed one |
| `8-kill-9` | `hi`, answer, `kill -9` | – idle busy idle; file left behind, deleted when run 9 started |
| `9-headless` | `claude -p "hi"` | – busy idle, deleted; `entrypoint: sdk-cli`, `kind: interactive` |
| `11-exit-without-prompt` | start, `/exit` without a prompt | – idle, deleted; `SessionEnd` still has a `prompt_id` (`/exit` gets one) |
| `12-tool-failure` | `ls` of a missing directory | – idle busy idle; `PostToolUseFailure` with `error`, `is_interrupt: false`, `duration_ms` |
| `13-file-tools` | `Write`, `Edit`, `Read`, `Grep`, `Glob` on `captures/s13.txt` | – idle busy idle |
| `14-sigterm-without-input` | started, terminated with SIGTERM before any input | – idle, deleted; `SessionEnd` `reason: other` **without `prompt_id`** |

– = the first snapshot, written before `status` is set.

## Findings

- **`status` values:** `idle`, `busy`, `waiting` with `waitingFor` (`permission prompt`, `input needed`, `dialog open`), `shell` (no turn running, a background shell still running). `waitingFor` is removed when waiting ends.
- **Interrupts:** Esc or Ctrl-C mid-turn or mid-tool, and a rejected permission, switch to `idle` within ~50 ms with no hook event (runs 2, 3, 4).
- **Lifetime:** the file appears before `SessionStart`, its first version without `status`. It is deleted on `/exit`, at the end of `claude -p` and on SIGTERM (run 14); after `kill -9` it stays until the next `claude` process starts (runs 6a → 7, 8 → 9).
- **`CLAUDE_CONFIG_DIR`** (run S10, no fixture): `claude` started with a fresh, empty config dir and no login created `<dir>/sessions/` with its `<pid>.<hash>.key` there and nothing in `~/.claude/sessions/`. The `<pid>.json` itself did not appear within 20 s of the onboarding screen; it needs a configured, logged-in session.
- **Identity:** one file per process, named by pid. Its `sessionId` can change: `--continue` (run 7), and a `claude bg-spare` process that took on a new session (pid 89359, outside these fixtures). Key by `sessionId`.
- **Writes:** mostly in place (same inode), sometimes by rename (`/exit`, end of `-p`). No snapshot was unparseable.
- **Hook drift against 2.1.285** (golden files unchanged, the mapping covers it):
  - `Agent` calls without `run_in_background` were launched async in interactive sessions (`tool_response.status: async_launched`, runs 6 and 6a): the orchestrator's `Stop` fires while they run.
  - A background agent's result comes back as `UserPromptSubmit` whose `prompt` starts with `<agent-message from="<agent_id>">` (run 6, 025 and 034, after the subagent called the new tool `SubagentHandback`, 023/024) or, as before, with `<task-notification>` (run 6a, 023).
  - `PermissionRequest` also fires for `AskUserQuestion` (run 4).
  - `PostToolUseFailure` (run 12, first capture): `tool_use_id`, `tool_name`, `tool_input`, `error`, `is_interrupt`, `duration_ms`. The mapping now maps it to core `tool.post`, block `tool.failure`. An Esc during a tool sent no post at all (run 3).
  - `SessionEnd` has no `prompt_id` when the session was terminated before any input (run 14, `reason: other`); `/exit` without a prompt still has one (run 11).
