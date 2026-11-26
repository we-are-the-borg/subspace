# Fixtures: Antigravity CLI 1.5.16 / 1.5.17 & Desktop App 2.35.1

Real hook payloads recorded on macOS (arm64) on 2026-11-25 with `tools/hook-capture/antigravity/`. These 130 files cover all six subscribed event types (`SessionStart`, `PreInvocation`, `PostInvocation`, `PreToolUse`, `PostToolUse`, `Stop`) across headless CLI (`agy -p`), interactive CLI (`agy`), and the desktop App (`Antigravity.app 2.35.1`).

Each `events/NNN-<hookEventName>.json` is an unchanged raw payload, anonymized as described in [`../../README.md`](../../README.md#anonymization). Its `expected/NNN-<hookEventName>.json` is `model/antigravity.json` applied to it: the target fields, core plus source block (golden file, [docs/model.md §7](../../../docs/model.md#7-golden-files)). Runs 1, 2, 3 and 7 include minimal edited transcript excerpts (`transcripts/excerpt.jsonl`), described below. Runs 3 and 7 also record the allowlisted terminal identifiers captured in `.meta` (`terminal.json`). No full transcripts, logger metadata, process ancestry or CLI JSONL streams are shipped.

Note on CLI version: runs 1, 5 and 6 were recorded under `agy 1.5.16`; `agy` auto-updated to `1.5.17` before runs 2, 3 and 4; run 7 was recorded in `Antigravity.app 2.35.1`. Payload shapes were identical across all three versions.

## Runs

| Run | Scenario | Events |
|---|---|---:|
| `1-headless-tools-failure-subagent` | Headless CLI (`agy -p`): `read_file`, `run_command` (`pwd` and `sh -c "exit 7"`), single `invoke_subagent` child conversation and `fullyIdle` transitions | 43 |
| `2-parallel-subagents` | Headless CLI (`agy -p`): two concurrent `invoke_subagent` calls in one turn, overlapping child hooks (`run_command`, `read_file`, `send_message`) and parent wakeups | 45 |
| `3-interactive-permission-approve-deny` | Interactive CLI (`agy --mode accept-edits --sandbox`) in Warp: Turn 1 approved (`1. Yes, run command`) with `PostToolUse`+`Stop`; Turn 2 denied (`4. No, cancel`) with no post/stop | 10 |
| `4-interactive-interrupt-mid-tool` | Interactive CLI (`agy --sandbox`): `sleep 30` interrupted mid-tool with `Esc` — no `PostToolUse`, `PostInvocation` or `Stop` | 3 |
| `5-resume` | Headless resume (`agy --conversation <run-1-id>`): no `SessionStart`, same `conversationId` and `transcriptPath`, `stepIdx` continues while `invocationNum`/`executionNum` reset | 7 |
| `6-cwd-with-spaces` | Workspace `cwd` containing spaces (`project with spaces`), inheriting ancestor `.agents/hooks.json` | 8 |
| `7-desktop-app-shared-host` | Desktop App (`Antigravity.app 2.35.1`): two conversations sharing one `language_server` `$PPID`, `__CFBundleIdentifier: com.google.antigravity`, `gemini-4-neon-high` | 14 |

## Edited transcript excerpts

Runs 1, 2, 3 and 7 include `transcripts/excerpt.jsonl` — selected records from `transcript_full.jsonl` (not full transcripts), each tagged with an added `conversation_id` field naming the conversation it came from, with paths anonymized like the payloads:

- **Run 1 (`1-headless-tools-failure-subagent/transcripts/excerpt.jsonl`):** parent `GENERIC` steps 6 (`pwd`), 9 (`sh -c "exit 7"` showing `Command exited with code 7`), 12 (`invoke_subagent` result naming child `conversationId`) and 14 (`SYSTEM_MESSAGE` reply from the child), plus child step 0 (`SYSTEM_MESSAGE` with `sender=<parent>`).
- **Run 2 (`2-parallel-subagents/transcripts/excerpt.jsonl`):** parent's two `invoke_subagent` `GENERIC` steps and both children's step 0 `SYSTEM_MESSAGE` records (`sender=<parent>`), establishing parent ↔ child correlation.
- **Run 3 (`3-interactive-permission-approve-deny/transcripts/excerpt.jsonl`):** step 6 (`status: "ERROR"`, `error: "permission check failed ... user denied permission to run command:"`), showing that user denial is recorded in the transcript even though no `PostToolUse` or `Stop` hook fires.
- **Run 7 (`7-desktop-app-shared-host/transcripts/excerpt.jsonl`):** `PLANNER_RESPONSE` records from both desktop App conversations (`model`, `input_tokens`, `output_tokens`, `cache_read_tokens`), with `thinking` replaced by `"<omitted>"`.

## Observed behavior

- **Silent exit 0 works on all 6 events:** empty stdout and stderr produced zero warnings or errors and never altered tool approval decisions. In Run 3 (`accept-edits`), `PreToolUse` fired before the permission prompt and the interactive dialog still appeared normally.
- **Subagents are separate conversations:** each `invoke_subagent` child gets its own `conversationId` and `transcriptPath`, fires all six hooks with `lastUserInput: ""`, and carries no parent ID field in hook payloads. Parent ↔ child links appear in the subagent's `send_message` hook (`toolCall.args.Recipient = <parent>`) and in both transcripts.
- **`PostToolUse` has no output and `error: ""` on nonzero shell exits:** `sh -c "exit 7"` (Run 1) produced `error: ""`; the exit code lives only in the transcript.
- **Denials and interrupts emit no terminal hooks:** both `4. No, cancel` (Run 3) and `Esc` mid-tool (Run 4) ended after `PreToolUse` with no `PostToolUse`, `PostInvocation` or `Stop`.
- **Resume emits no `SessionStart`:** Run 5 started directly with `PreInvocation` (`invocationNum: 0`, `initialNumSteps: 20`).
- **Desktop App shares one host process:** both conversations in Run 7 shared the same `language_server` `$PPID` and carried `__CFBundleIdentifier: com.google.antigravity`.

## Evidence limits

This capture set covers macOS arm64 only. Unobserved: `antigravity-ide`, installed-plugin `$PLUGIN_DATA` inside `Antigravity.app`, `Stop.terminationReason` values other than `NO_TOOL_CALL`, background shell commands (`fullyIdle: false` without subagents), `/swarm`, mid-session model switching, and Linux/WSL/native Windows.
