# Fixtures: Codex CLI 0.159.3

Real hook payloads recorded on macOS 27.0 (arm64) on 2026-10-01 with `tools/hook-capture/codex/`. These 108 files cover all eleven subscribed event types. Consumers should correlate events with `session_id`, `turn_id`, `agent_id` and `tool_use_id`; file order records delivery order and is not a lifecycle guarantee.

Each `events/NNN-<hook_event_name>.json` is an unchanged raw payload, anonymized as described in [`../../README.md`](../../README.md#anonymization). Its `expected/NNN-<hook_event_name>.json` is `model/codex.json` applied to it: the target fields, core plus source block (golden file, [docs/model.md §7](../../../docs/model.md#7-golden-files)). Scenario 1 also includes an edited rollout metadata excerpt, described below. No full rollouts, logger metadata, process ancestry or CLI output JSONL are shipped. The three-event preparation smoke test was not duplicated because it adds no scenario beyond startup, prompt and stop.

## Runs

| Run | Scenario | Events |
|---|---|---:|
| `1-headless-parallel-reused-child-failure` | Headless root, overlapping child turns, child reuse and a failed shell command | 28 |
| `2-daemon-permission-compact` | Shared app-server host, automatic permission review and manual compaction | 18 |
| `3-manual-permission-remembered-rejection` | Manual approval, confirmed rejection UI action and remembered approval | 19 |
| `4-pretool-interrupt-recovery` | Turn interrupted before a tool call, followed by a successful turn | 7 |
| `5-pretool-interrupt-exit` | Turn interrupted before a tool call, then immediate CLI shutdown | 3 |
| `6-running-sleep-recovery` | Running shell wait interrupted, recovery turn, then late post event | 9 |
| `7-running-sleep-exit` | Running shell wait interrupted, then immediate CLI shutdown | 4 |
| `8-resume` | Resumed daemon session with the original session and transcript IDs | 7 |
| `9-ephemeral` | Headless ephemeral session with null transcript paths | 5 |
| `10-cwd-with-spaces` | Inherited hooks from a cwd containing spaces, plus a running-shell interrupt | 8 |

## Edited rollout metadata excerpt

Scenario 1's [rollouts/session_meta.jsonl](1-headless-parallel-reused-child-failure/rollouts/session_meta.jsonl) contains only the first `session_meta` line of the root, `/root/alpha` and `/root/beta` rollouts, in that order. It is an **edited excerpt**, not a full rollout. To remove account identifiers and omit the runtime instructions, these three fields were changed in each record:

- `payload.creator_user_id` → `"user-REDACTED"`
- `payload.creator_account_id` → `"00000000-0000-0000-0000-000000000000"`
- `payload.base_instructions.text` → `"<omitted>"`

All other bytes in those lines remain as captured (paths, git remote and commit hash anonymized like the payloads), including timestamps and the branch name. The unchanged thread IDs, parent IDs and `source.subagent.thread_spawn.agent_path` let consumers test child-to-spawn correlation against the unchanged hook payloads. The full local rollouts establish the additional output, exit-status and timing observations below; the excerpt cannot test those observations.

## Observed behavior

- Child events retain the root `session_id`; `agent_id` identifies the child. One `SubagentStart` can have multiple `SubagentStop` events because a child can be reused for another turn.
- A `PostToolUse` does not prove command success. The failed `exit 7` call has a post event with an empty response; its exit status exists only outside the hook payload.
- `PermissionRequest` has no `tool_use_id`. Remembered approval can remove the permission event from a repeated call.
- An `Interrupt` can have no post event, or a matching post can arrive after a later turn's `Stop`.
- `SessionStart.source` distinguishes `startup`, `compact` and `resume`. Ephemeral sessions use `transcript_path: null` on every event.

## Evidence limits

This capture set does not establish nested child spawning, child reuse across resume, concurrent identical permission requests, process termination after interruption, Linux/WSL/native Windows behavior, MCP-specific visibility, or installed-plugin data/trust/uninstall behavior. The space-path run covers the project cwd on macOS, not an installed plugin path. Missing posts or stops at shutdown are delivery observations and do not prove whether a child process exited.
