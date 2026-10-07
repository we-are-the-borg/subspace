# Fixtures: Claude Code 2.1.285

Real hook payloads recorded on 2026-09-30 with `tools/hook-capture/` (all 28 subscribed events, `async: true`, macOS). Both apps test their Claude Code adapters against these files.

## Layout

```
<run>/
├── events/NNN-<hook_event_name>.json   # raw payload, byte for byte, numbered in arrival order (file mtime)
└── expected/NNN-<hook_event_name>.json # model/claude-code.json applied to it: target fields, core + block (docs/model.md §7)
```

Payloads are unchanged, anonymized as described in [`../../README.md`](../../README.md#anonymization). Transcripts are not included.

## Runs

| Run | What happened | Events |
|---|---|---|
| `1-headless-parallel-subagents` | `claude -p`, Haiku, two parallel `general-purpose` subagents (`Bash`, `Read`) running in the foreground | 21 |
| `2-interactive-background-subagents-compact-exit` | interactive, same prompt; the subagents ran **in the background**; then `/compact`, `/model sonnet`, `/exit` | 34 |
| `3-interactive-permission-ctrl-c` | interactive, `hi`; Claude read a file outside the project and asked for permission (approved after ~13 s); ended with Ctrl-C twice | 11 |

## Findings

- **`agent_id`/`agent_type` are set on every event inside a subagent**, including its `PreToolUse`, `PostToolUse` and `PostToolBatch`. Main-thread events have neither.
- **`$PPID` is the `claude` process** in all 66 events and equals `CLAUDE_PID`, which Claude Code exports to hooks. No intermediate shell.
- **`SessionEnd` arrives with async hooks** in all three runs: `reason` `other` (`-p`), `prompt_input_exit` (`/exit` and Ctrl-C).
- **Arrival order:** no `PostToolUse` arrived before its `PreToolUse`, no `SubagentStop` before its `SubagentStart`. The sample is small; the contract still requires correlation via IDs.
- **Background subagents (run 2):** `PostToolUse` for `Agent` arrives immediately after launch; the orchestrator's `Stop` fires while they run; each result returns as `UserPromptSubmit` with a `prompt` starting with `<task-notification>`. `Stop` and `SubagentStop` carry `background_tasks`, a snapshot of running background agents.
- **Internal agents (run 2):** three `SubagentStop` events with empty `agent_type` and no matching `SubagentStart`, one of them the compaction summary. Their `agent_transcript_path` points to files that don't exist.
- **Permissions (run 3):** `PermissionRequest` came 30 ms after `PreToolUse`, the `permission_prompt` `Notification` 6 s later.
- **`/compact`** yields `PreCompact`, `SessionStart` (`source: compact`) and `PostCompact` (with `compact_summary`).
- **`/model sonnet`** yielded `PostModelSwitch` with `source: auto` and `requested_model: null`, plus cost fields (`context_tokens`, `estimated_cache_write_usd`).
- **`ConfigChange`** fired twice for `.claude/settings.local.json` in the project.
- **Sizes:** largest payload 5.4 KB (`PostToolBatch`), 91 KB for all 66 events. These runs read small files only; large `Read`/`Write` payloads are not covered.
- **Not fired:** `Setup`, `UserPromptExpansion`, `PermissionDenied`, `PostToolUseFailure`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `StopFailure`, `CwdChanged`, `DirectoryAdded`, `Elicitation`, `ElicitationResult`. Their shape is known only from the hooks reference.
