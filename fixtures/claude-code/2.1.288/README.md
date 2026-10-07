# Fixtures: Claude Code 2.1.288

Real hook payloads and session status files, recorded on 2026-10-03 on macOS with `tools/hook-capture/claude-code/drive-session-runs.py S15`. Layout, numbering and `timeline.jsonl` as in [`../2.1.287/README.md`](../2.1.287/README.md). Payloads and status files are unchanged, anonymized as described in [`../../README.md`](../../README.md#anonymization). Transcripts are not included.

## Runs

| Run | What happened | Status sequence |
|---|---|---|
| `15-stop-background-agent` | Sonnet; one `Agent` call with `run_in_background: true` whose subagent runs four `sleep 10` steps; after the orchestrator's `Stop` the driver pressed Ctrl+X Ctrl+K twice (stop all background agents); then `Reply with the word ok.`; `/exit` 60 s later | – idle busy … busy idle, deleted: `busy` from the first prompt until the `ok` turn ended |

## Findings

- **A stopped background agent sends no `SubagentStop`.** Agent `a80f925acc1e94159` (`SubagentStart` 009, `PostToolUse(Agent)` 010 with `status: async_launched`) ran `sleep 10; echo one` (`PreToolUse` 012) when it was stopped. No `PostToolUse` for that call and no `SubagentStop` for the agent followed, also not in the 60 s before `/exit`.
- **It only disappears from the snapshot.** `background_tasks` on `Stop` 013 and on the internal agent's `SubagentStop` 014 lists it as `running`; the next `Stop` (018) has `[]`. The mapping's `background_agents` gives `["a80f925acc1e94159"]` and then `[]`.
- **The stop is announced as a turn.** `UserPromptSubmit` 017 has the `prompt` `Background agent "Run sleep commands" was stopped by the user.`: the `Agent` call's `description`, no agent ID. Its turn ends with `Stop` 018. The same chord also sent 016, a `<task-notification>` of type `artifact-auto-react` that belongs to Claude Code's artifact feature, not to the agent; that turn got no `Stop` of its own.
- Internal agents (`agent_type: ""`, no `SubagentStart`) stopped at 014, 025 and 026; 022/024 show one of them running a tool.
- The status file stayed `busy` from the first prompt until the `ok` turn ended (023), across `Stop` 013 and 018, as in run 6 of 2.1.287.
- Hook drift against 2.1.287: none that touches a target field (`tools/e2e/check.sh` passes for the real events of 2026-10-03).
