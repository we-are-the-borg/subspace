# Fixtures: Codex CLI 0.167.0

Real hook payloads recorded on macOS 27.0 (arm64) with `tools/hook-capture/codex/drive-review-runs.py`: runs 1–3 on 2026-11-07 (README runs 2c–2e, issue #34), run 4 on 2026-11-09 (README run 2f, issue #38). `codex-cli 0.167.0` from the repository root, one prompt per turn, the hook events taken from the installed subspace plugin's spool. Run 1 and 2 use automatic review (`codex --approve-for-me`; `/status` shows `Permissions: Workspace (Approve for me)` and, in this version, no `Server` row, so daemon attachment is not established); run 3 the manual reviewer (`--no-daemon -a on-request -s workspace-write -c 'approvals_reviewer="user"'`), answered by the driver; run 4 starts at low reasoning effort (`--no-daemon -a on-request -s workspace-write -c 'model_reasoning_effort="low"'`, the reviewer from the capture machine's config: `auto_review`).

Each `events/NNN-<hook_event_name>.json` is the unchanged raw payload taken from the envelope (`payload`), anonymized as described in [`../../README.md`](../../README.md#anonymization), in delivery order (file time). Its `expected/NNN-<hook_event_name>.json` is `model/codex.json` applied to it (golden file, [docs/model.md §7](../../../docs/model.md#7-golden-files)). The hooks these runs cover carry the same keys as in 0.159.3, root and child events alike; only run 4 has a child (one `spawn_agent`). Short references as in `docs/model.md`: **R2-004** is `2-…/events/004-*.json`.

## Runs

| Run | Scenario | Events |
|---|---|---:|
| `1-auto-review-approvals` | Automatic review approves four requests: a write outside the workspace, a network call with `sleep 10`, two concurrent network calls in one turn, a POST of a missing file | 24 |
| `2-auto-review-rejection` | Automatic review rejects `curl -fsSL … \| sh` (turn 1), then approves an `rm -rf` and a `chmod -R` of a missing directory | 15 |
| `3-manual-review-approval-denial` | Manual reviewer: one approval (`y`), one denial (Esc) | 10 |
| `4-effort-levels` | Reasoning effort per turn: `echo one` at low, `/model` to high for this session, `echo two`, then one child agent running `echo three` | 19 |

The same workload as run 1 on 0.166.0 gave the same sequence (not shipped).

## Rollout excerpts

Each run has `rollouts/excerpt.jsonl`, an **edited excerpt** of its rollout, not a full one:

- every `turn_context` record, its `payload` reduced to `turn_id`, `root_turn_id`, `approval_policy`, `approvals_reviewer`, `model` and `effort`, in the record's key order (the record also carries sandbox paths, the model's instructions and settings);
- unchanged: the tool output of the rejected call (run 2) and of the denied call plus the `turn_aborted` record (run 3), paths anonymized.

Run 4's excerpt holds the root rollout's records first (lines 1–3), then the child's (line 4, from the rollout that R4-013's `transcript_path` names); a child record has a `root_turn_id` other than its `turn_id`.

## Findings

- **Who answers:** no payload field tells. `PermissionRequest` has `permission_mode: "default"` under both reviewers (R1-004, R3-004) and the same keys as in 0.159.3; no hook marks a decision. The turn's `turn_context` record in the rollout (same `turn_id`) names the effective reviewer: `approvals_reviewer: "auto_review"` (runs 1, 2) or `"user"` (run 3).
- **Order:** `PreToolUse` came before `PermissionRequest` in every request of every run, 10–26 ms apart (file time), under both reviewers (R1-003/004, R3-003/004). 0.159.3 had both orders (X2, X3), so the order is not a reviewer signal.
- **Concurrent requests** (R1-013…016): both `PreToolUse`, then both `PermissionRequest` in the opposite order; the commands differ, so matching by command assigns them.
- **Approval** (either reviewer): `PostToolUse` of the call after the command ran (R1-005, R3-005): 2.4–13.5 s after the request under automatic review (runs 1, 2; the reviewer's own time included), 1.2 s after the user's answer (run 3).
- **Rejection by the automatic reviewer** (R2-003…005): no `PostToolUse` and no `Interrupt`; the turn goes on and ends with `Stop` 10.5 s after the request. The rollout records the rejection only as the call's output text (`exec_command failed: CreateProcess { message: "Rejected(\"This action was rejected due to unacceptable risk.\nReason: …` in the excerpt); there is no structured decision record, and no `CommandExecution` item for the call.
- **Denial by the user** (R3-008…010): `Interrupt`, no `PostToolUse` and no `Stop`, as in X3; the rollout has the output `aborted by user after 1.2s` and `turn_aborted` with `reason: interrupted`.
- **Not observed:** the automatic reviewer handing a request to the user, a further tool call in a turn after a rejection, sessions of the ChatGPT app.

## Reasoning effort

No hook payload carries the effort; `model` is in every payload (R4-001…019), `effort` only in the rollout's `turn_context` record of the turn (same `turn_id`). Run 4 (`4-effort-levels/rollouts/excerpt.jsonl`, lines L1–L4):

| Turn | Events | Excerpt | `model` | `effort` |
|---|---|---|---|---|
| 1, `echo one`, started with `-c 'model_reasoning_effort="low"'` | R4-002…005 | L1 | `gpt-6.1-sol` | `low` |
| 2, `echo two`, after the switch | R4-006…009 | L2 | `gpt-6.1-sol` | `high` |
| 3, `spawn_agent` and `wait_agent` | R4-010…012, 014, 018, 019 | L3 | `gpt-6.1-sol` | `high` |
| child `/root/capture`, `echo three` | R4-013, 015…017 | L4 | `gpt-5.6-luna` | `medium` |

- **Switch:** `/model` changes the effort within the session. The picker (`Select Model and Effort`) lists the models with the current one marked; picking it opens `Select Reasoning Level for GPT-6.1-Sol` with `Low (default) (current)`, `Medium`, `High`, `Extra high` and `More reasoning…` (Max and Ultra), keys `enter default · s session · esc back`. The driver chose High with `s`; Codex answered `Model changed to gpt-6.1-sol high for this session only`, the status line and `/status` then showed `high`. Enter (`default`) would set the global default instead (not tried; the capture machine's `config.toml` was unchanged after the run). No resume was needed. The next turn's `turn_context` has the new value (L2); turn 1's stays `low` (L1).
- **Child:** its `turn_context` (L4, `root_turn_id` = turn 3) carries its own `model` and `effort`, not the parent's `high`. The spawn call set neither (its arguments: `task_name`, `fork_turns`, `message`); the capture machine's config sets a default model and effort for subagents (`[agents] default_subagent_model`, `default_subagent_reasoning_effort`), which these values match. The child's hook payloads carry `model: "gpt-5.6-luna"` (R4-013, 015…017).
- **Type:** `effort` is a JSON string in every `turn_context` of all four runs; none lacks it. Runs 1–3 have `effort: "high"` with `model: "gpt-6.1-sol"` in every record (their excerpts).
- **Values observed:** `low`, `medium`, `high`. Not observed: `none`, `minimal`, `xhigh`, and the picker's Max and Ultra.
- The full local rollout also records the switch outside `turn_context`, which the excerpt does not keep: an `event_msg` `thread_settings_applied` with `thread_settings.reasoning_effort: "high"` when `/model` was confirmed, and before turn 2's model request a `response_item` `configuration_update` with `reasoning.effort: "high"`. For the child, the parent's rollout has an `event_msg` `item_completed` with a `SubAgentActivity` item (`kind: "started"`, turn 3) carrying `model: "gpt-5.6-luna"` and `reasoning_effort: "medium"`; its `kind: "completed"` item has both `null`.
