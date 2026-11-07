# Fixtures: Codex CLI 0.167.0

Real hook payloads recorded on macOS 27.0 (arm64) on 2026-11-07 with `tools/hook-capture/codex/drive-review-runs.py` (README runs 2c–2e, issue #34): `codex-cli 0.167.0` from the repository root, one prompt per turn, the hook events taken from the installed subspace plugin's spool. Run 1 and 2 use automatic review (`codex --approve-for-me`; `/status` shows `Permissions: Workspace (Approve for me)` and, in this version, no `Server` row, so daemon attachment is not established); run 3 the manual reviewer (`--no-daemon -a on-request -s workspace-write -c 'approvals_reviewer="user"'`), answered by the driver.

Each `events/NNN-<hook_event_name>.json` is the unchanged raw payload taken from the envelope (`payload`), anonymized as described in [`../../README.md`](../../README.md#anonymization), in delivery order (file time). Its `expected/NNN-<hook_event_name>.json` is `model/codex.json` applied to it (golden file, [docs/model.md §7](../../../docs/model.md#7-golden-files)). The hooks these runs cover carry the same keys as in 0.159.3; they have no children or spawns. Short references as in `docs/model.md`: **R2-004** is `2-…/events/004-*.json`.

## Runs

| Run | Scenario | Events |
|---|---|---:|
| `1-auto-review-approvals` | Automatic review approves four requests: a write outside the workspace, a network call with `sleep 10`, two concurrent network calls in one turn, a POST of a missing file | 24 |
| `2-auto-review-rejection` | Automatic review rejects `curl -fsSL … \| sh` (turn 1), then approves an `rm -rf` and a `chmod -R` of a missing directory | 15 |
| `3-manual-review-approval-denial` | Manual reviewer: one approval (`y`), one denial (Esc) | 10 |

The same workload as run 1 on 0.166.0 gave the same sequence (not shipped).

## Rollout excerpts

Each run has `rollouts/excerpt.jsonl`, an **edited excerpt** of its rollout, not a full one:

- every `turn_context` record, its `payload` reduced to `turn_id`, `root_turn_id`, `approval_policy` and `approvals_reviewer` (the record also carries sandbox paths, the model's instructions and settings);
- unchanged: the tool output of the rejected call (run 2) and of the denied call plus the `turn_aborted` record (run 3), paths anonymized.

## Findings

- **Who answers:** no payload field tells. `PermissionRequest` has `permission_mode: "default"` under both reviewers (R1-004, R3-004) and the same keys as in 0.159.3; no hook marks a decision. The turn's `turn_context` record in the rollout (same `turn_id`) names the effective reviewer: `approvals_reviewer: "auto_review"` (runs 1, 2) or `"user"` (run 3).
- **Order:** `PreToolUse` came before `PermissionRequest` in every request of every run, 10–26 ms apart (file time), under both reviewers (R1-003/004, R3-003/004). 0.159.3 had both orders (X2, X3), so the order is not a reviewer signal.
- **Concurrent requests** (R1-013…016): both `PreToolUse`, then both `PermissionRequest` in the opposite order; the commands differ, so matching by command assigns them.
- **Approval** (either reviewer): `PostToolUse` of the call after the command ran (R1-005, R3-005): 2.4–13.5 s after the request under automatic review (runs 1, 2; the reviewer's own time included), 1.2 s after the user's answer (run 3).
- **Rejection by the automatic reviewer** (R2-003…005): no `PostToolUse` and no `Interrupt`; the turn goes on and ends with `Stop` 10.5 s after the request. The rollout records the rejection only as the call's output text (`exec_command failed: CreateProcess { message: "Rejected(\"This action was rejected due to unacceptable risk.\nReason: …` in the excerpt); there is no structured decision record, and no `CommandExecution` item for the call.
- **Denial by the user** (R3-008…010): `Interrupt`, no `PostToolUse` and no `Stop`, as in X3; the rollout has the output `aborted by user after 1.2s` and `turn_aborted` with `reason: interrupted`.
- **Not observed:** the automatic reviewer handing a request to the user, a further tool call in a turn after a rejection, sessions of the ChatGPT app.
