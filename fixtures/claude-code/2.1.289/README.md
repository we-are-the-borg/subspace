# Fixtures: Claude Code 2.1.289

Real hook payloads and session status files, recorded on 2026-10-05 on macOS with `tools/hook-capture/claude-code/drive-session-runs.py S16` and `… S17 S18`. Layout, numbering and `timeline.jsonl` as in [`../2.1.287/README.md`](../2.1.287/README.md). Payloads and status files are unchanged, anonymized as described in [`../../README.md`](../../README.md#anonymization). Transcripts are not included.

## Runs

| Run | What happened | Status sequence |
|---|---|---|
| `16-agent-model` | Sonnet; two `Agent` calls in one message, `general-purpose`, the first with `model: haiku`, the second without; both launched async, results handed back as `<agent-message …>`; `/exit` 20 s after the second `SubagentStop` | – idle busy idle, deleted |
| `17-model-clear` | Haiku; one prompt; `/model sonnet`, confirmed in the dialog "Switch model?"; `/clear`; one prompt; `/exit` | – idle busy idle **waiting** (`dialog open`) idle, **new `sessionId`** idle busy idle, deleted |
| `18-continue-other-model` | `claude --model haiku --continue`: resumes run 17's second session, which last ran on Sonnet; one prompt; `/exit` | – – idle busy idle, deleted: the first snapshot carries a fresh `sessionId`, the second the resumed one |

## Findings

- **`tool_input.model` is an alias and optional.** `PreToolUse` 008 has `model: haiku`; 009 has no `model` key.
- **`tool_response.resolvedModel` names the model in every case.** The `PostToolUse` of each call has the full ID: `claude-haiku-4-5-20251001` for the `haiku` call (012), `claude-sonnet-5-5` for the call without `model` (011), which inherited the orchestrator's model. The subagent transcripts agree (`message.model`). Older captures have the key too (2.1.285 C1-016, C2-008; 2.1.287 S6-010; 2.1.288 S15-010).
- `SubagentStart` (010, 013) still names no model.
- **`SessionStart` after `/clear` has no `model`** (17-015: `cwd`, `hook_event_name`, `scratchpad_dir`, `session_id`, `source: clear`, `transcript_path`), and neither has the one of `--continue` (18-003, `source: resume`, with the cache keys as in 2.1.287 S7-003). Only the `startup` one has it (17-002).
- **`/clear` keeps the process's model.** `PostModelSwitch` 17-011 (`source: command`, `from_model: claude-haiku-4-5-20251001`, `to_model: claude-sonnet-5-5`, `requested_model: sonnet`); after `/clear` the new session's first answer came from `claude-sonnet-5-5` (transcript `message.model`).
- **`/clear` ends and starts within one process:** `SessionEnd` 17-014 (`reason: clear`, with a `prompt_id`) and `SessionStart` 17-015 of the new session 21 ms apart, same `CLAUDE_PID`. The status file switched to the new `sessionId` (17-013) just before them, in place.
- **Resume takes the new process's model.** Run 18 resumed a session that last ran on Sonnet, with `--model haiku`: the answer came from `claude-haiku-4-5-20251001` (transcript). Nothing in the hook payloads or the status file names it.
- No hook payload, status file or `CLAUDE_*` variable in the hooks' environment (`log.sh` records their names) carries the model elsewhere.
- **Side effect of run 17:** `/model sonnet` saves `sonnet` as the default model in `~/.claude/settings.json` (transcript: "saved as your default for new sessions"); reset it by hand after the run.
- Drift against 2.1.288: none. Hook payloads and the status file have the same keys as the 2.1.288 run.
