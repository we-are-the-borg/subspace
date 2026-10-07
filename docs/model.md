# Target fields and mapping documents

The plugins ship the mapping documents to `$ROOT/model/<source>.json` (contract §12); the apps' interpreters are still to come.

**The idea.** Event files stay exactly as contract v1 defines them: the agent's raw payload, byte for byte, in the v1 envelope. subspace additionally publishes one **mapping document** per source ([`model/claude-code.json`](../model/claude-code.json), [`model/codex.json`](../model/codex.json)). It says where in the raw payload each **target field** is. Apps apply it with a small generic interpreter (§5). When an agent changes its payloads, subspace changes the mapping document and releases; the apps need no update.

The result of applying a mapping to one payload looks like this:

```json
{"kind":"tool.post","session":"…","tool_call":"call_…","tool":"spawn_agent","cwd":"…",
 "codex":{"kind":"tool.post","turn_id":"…","rollout_path":"…","tool_name":"collaborationspawn_agent",
          "tool_response":"{\"task_name\":\"/root/alpha\"}","spawn_name":"alpha","spawn_task":"/root/alpha", …}}
```

It is a small **core** with the same meaning for every source, plus **one block per source** (`claude_code` or `codex`), chosen by the envelope's `source`. Each block has its own kinds, fields and correlation rules. A name is never given two meanings, not across sources and not across hooks of one source.

**What the mapping solves and what it doesn't.** It answers "where is the value": a renamed, moved or newly added key is handled by changing the mapping alone. It doesn't answer "what does it mean": when an event changes its meaning or new semantics arrive (for example a link field that enables a new correlation rule), apps still change their logic.

**Evidence.** Every mapping is derived from the real captures in `fixtures/claude-code/2.1.285/`, `fixtures/claude-code/2.1.287/`, `fixtures/claude-code/2.1.288/`, `fixtures/claude-code/2.1.289/` and `fixtures/codex/0.159.3/`, and nothing else. Short references: **C2-014** is `fixtures/claude-code/2.1.285/2-…/events/014-*.json`, **S4-010** is `fixtures/claude-code/2.1.287/4-…/events/010-*.json` or `…/status/010-status.json` (S15 is in `2.1.288/15-…`, S16–S18 in `2.1.289/16-…` to `18-…`), **X1-008** is `fixtures/codex/0.159.3/1-…/events/008-*.json`. The runs:

- Claude Code 2.1.285: C1 headless parallel subagents; C2 interactive background subagents, compact and exit; C3 permission and Ctrl-C.
- Claude Code 2.1.287, hook events plus session status files (§12): S1 idle and exit; S2 Esc and Ctrl-C mid-turn; S3 Esc mid-tool; S4 permission and question waits; S5 `!` shell; S6 background subagents; S6a background shell, exit dialog, killed; S7 `--continue`; S8 `kill -9`; S9 `claude -p`; S11 `/exit` without a prompt; S12 failing tool; S13 file tools; S14 terminated before any input.
- Claude Code 2.1.288, hook events plus session status files: S15 a background agent stopped by the user (Ctrl+X Ctrl+K).
- Claude Code 2.1.289, hook events plus session status files: S16 two `Agent` calls, one with `model: haiku`, one without; S17 `/model sonnet`, then `/clear` in the same process; S18 `--continue` of S17's session with `--model haiku`.
- Codex: X1 parallel and reused children plus a failed command; X2 daemon permission and compact; X3 manual permission and rejection; X4/X5 interrupt before a tool; X6/X7 interrupt of a running shell; X8 resume; X9 ephemeral; X10 cwd with spaces.

## 1. Principles

- **Raw stays on disk.** The hook and the contract v1 envelope don't change. The mapping is a view, applied when reading. Anything a target field doesn't cover is still in `payload`.
- **Stateless per event.** A target field is a pure function of one payload. The mapping reads no side file (transcripts, rollouts, `meta.json`) and knows nothing about other events.
- **Only what apps need.** The target fields cover what The Collective and Unimatrix Zero use today (§9). Agent-defined open structures (`tool_input`, `tool_response`, `background_tasks`) are **opaque**: a target field points at the raw value, with no claims about its inside, except where a named field picks one stable value out of it (`command`, `spawn_task`, …).
- **Absent, never guessed.** A target field is absent when its path is missing, its value has another type, or the interpreter can't evaluate the rule. Apps treat absent as "unknown".
- **Tolerant to versions.** Payloads don't reliably say which agent version wrote them. Drift is absorbed by fallback paths and type checks in the mapping, never by switching on a version. An old event file must stay readable with a newer mapping.
- **Only what the captures show.** A target field is defined for the hooks where a fixture shows its key. One exception is a key the agent documents but doesn't send yet (Claude Code's `parent_tool_use_id`): the mapping names it so it is picked up once it appears, and says so.

## 2. Core

| Field | Type | From the payload | Meaning |
|---|---|---|---|
| `kind` | string, always present | `hook_event_name` via a table (§2.1) | Coarse kind with the same meaning in both sources, else `other`, or `unknown` |
| `session` | non-empty string | `session_id` | The root session; also on subagent/child events (C1-009, X1-010) |
| `agent` | non-empty string | `agent_id` | Set only on events of a subagent/child thread; absent = the root (C1-009, X1-010 vs. C1-005, X1-007) |
| `tool_call` | non-empty string | `tool_use_id`, on `PreToolUse`/`PostToolUse` (Claude Code also `PostToolUseFailure`) | Pairs a tool call's pre and post (C1-005/016, X1-003/004) |
| `tool` | string | `tool_name` via a table (§2.2), on `PreToolUse`, `PostToolUse`, `PermissionRequest` (Claude Code also `PostToolUseFailure`) | Coarse tool category |
| `cwd` | string | `cwd` | Working directory, every event (C1-001, X10-001) |

### 2.1 Core kinds

| Core `kind` | Meaning in both sources | Claude Code hook | Codex hook |
|---|---|---|---|
| `session.start` | A session started, resumed or restarted after compaction | `SessionStart` (C1-001, C2-032) | `SessionStart` (X1-001, X2-014, X8-001) |
| `turn.start` | A prompt starts a root turn | `UserPromptSubmit` (C1-004, C2-021) | `UserPromptSubmit` (X1-002) |
| `turn.stop` | A root turn completed normally | `Stop` (C1-020, C2-014) | `Stop` (X1-028, X2-006) |
| `tool.pre` | A tool call starts | `PreToolUse` (C1-005) | `PreToolUse` (X1-003) |
| `tool.post` | A tool call ended; says nothing about success | `PostToolUse` (C1-011), `PostToolUseFailure` (S12-009) | `PostToolUse` (X1-004, X1-006) |
| `permission.request` | The agent waits for an approval of a tool call | `PermissionRequest` (C3-006) | `PermissionRequest` (X2-004) |
| `agent.start` | A subagent/child thread starts | `SubagentStart` (C1-006) | `SubagentStart` (X1-009) |
| `compact.start` / `compact.end` | Context compaction starts / ended | `PreCompact`/`PostCompact` (C2-029/033) | `PreCompact`/`PostCompact` (X2-012/013) |
| `other` | A known event without a shared meaning: read the block's `kind` | all other known hooks | `SubagentStop`, `Interrupt` |
| `unknown` | A hook the mapping doesn't know | | |

Left out of the core on purpose: Claude Code's `SubagentStop` ends a subagent, while Codex's ends one child turn (X1-014 and X1-026 are one child). Codex's `Interrupt` has no Claude Code counterpart. Claude Code's `StopFailure` is unobserved.

### 2.2 Core tool categories

| Core `tool` | Claude Code `tool_name` | Codex `tool_name` |
|---|---|---|
| `shell` | `Bash` (C1-009) | `Bash` (X1-003) |
| `spawn_agent` | `Agent` (C1-005) | `collaborationspawn_agent` (X1-007) |
| `other` | everything else, e.g. `Read` (C3-005) | everything else, e.g. `collaborationwait_agent` (X1-018) |

A category exists only where a tool exists in both sources. The raw name is the block's `tool_name`.

### 2.3 Rules that hold for the core

- Arrival order is only a hint (contract §6). Pair `tool.pre` ↔ `tool.post` by (`session`, `agent` or root, `tool_call`). Either may arrive first (X6-009 arrives after a later turn's stop).
- `agent` absent means the root thread; present means the event belongs to that subagent/child.
- `turn.start`, `tool.pre`, `permission.request` and `agent.start` mean "active". `turn.stop` means a root turn completed. Which turn it closes, and how a turn ends otherwise, is source-specific (§3.3, §4.3).
- `permission.request` has no `tool_call` in either source (C3-006, X2-004). Matching it is source-specific.

## 3. Claude Code (`claude_code`)

### 3.1 Kinds

| Hook | Block `kind` | Core `kind` | Observed |
|---|---|---|---|
| `SessionStart` | `session.start` | `session.start` | C1-001, C2-001, C2-032, C3-001 |
| `SessionEnd` | `session.end` | `other` | C1-021, C2-034, C3-011 |
| `InstructionsLoaded` | `instructions.load` | `other` | C1-002 |
| `ConfigChange` | `config.change` | `other` | C2-004, C2-028 |
| `UserPromptSubmit` | `turn.start` | `turn.start` | C1-004, C2-021 |
| `PreToolUse` | `tool.pre` | `tool.pre` | C1-005 |
| `PermissionRequest` | `permission.request` | `permission.request` | C3-006 |
| `PostToolUse` | `tool.post` | `tool.post` | C1-011 |
| `PostToolUseFailure` | `tool.failure` (the call failed) | `tool.post` | S12-009 |
| `PostToolBatch` | `tool.batch` | `other` | C1-012 |
| `Notification` | `notification` | `other` | C3-007 |
| `SubagentStart` | `agent.start` | `agent.start` | C1-006 |
| `SubagentStop` | `agent.stop` (the subagent finished) | `other` | C1-015, C2-025 |
| `Stop` | `turn.stop` | `turn.stop` | C1-020 |
| `PreCompact` | `compact.start` | `compact.start` | C2-029 |
| `PostCompact` | `compact.end` | `compact.end` | C2-033 |
| `PostModelSwitch` | `model.change` | `other` | C2-030 |
| `Setup`, `UserPromptExpansion`, `PermissionDenied`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `StopFailure`, `CwdChanged`, `DirectoryAdded`, `Elicitation`, `ElicitationResult` | `setup`, `prompt.expand`, `permission.denied`, `task.create`, `task.complete`, `teammate.idle`, `turn.failure`, `cwd.change`, `directory.add`, `elicitation.request`, `elicitation.result` | `other` | unobserved |
| anything else | `unknown` | `unknown` | – |

Unobserved hooks get their kind and the fields that hold on every hook (`transcript_path`, `prompt_id`, …). Everything else about them stays in `payload` until a capture adds fields.

### 3.2 Fields, Claude Code 2.1.285

| Block field | Type | From the payload, on which hooks | Evidence |
|---|---|---|---|
| `kind` | string | `hook_event_name` via §3.1 | |
| `transcript_path` | string | `transcript_path`, every hook; the session's transcript, also inside subagents | C1-001, C1-009 |
| `prompt_id` | non-empty string | `prompt_id`, every hook after the first prompt | C1-004; absent C1-001…003 |
| `permission_mode` | string | `permission_mode` | C1-004, C2-031 (`plan`) |
| `agent_type` | string, **may be empty** | `agent_type`, subagent events | C1-009; `""` C2-025 |
| `start_source` | string | `source` on `SessionStart` | C1-001 `startup`, C2-032 `compact`, S7-003 `resume`, S17-015 `clear` |
| `model` | string | `model` on `SessionStart`: the model the process starts the session with. **Only on an interactive `startup` and on `compact`**; absent on `clear`, `resume` and headless (`claude -p`). See §3.3 "Session model" | C2-001, C2-032, S17-002; absent S17-015 (`clear`), S7-003 and S18-003 (`resume`), C1-001 and S9-004 (headless) |
| `end_reason` | string | `reason` on `SessionEnd` | C1-021 `other`, C2-034 `prompt_input_exit`; S14-006 `other` for a session terminated from outside before any input, which has no `prompt_id` |
| `prompt` | string | `prompt` on `UserPromptSubmit` | C1-004; `<task-notification>` C2-021; `<agent-message …>` S6-025 |
| `tool_name` | string | `tool_name` on `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest` | C1-005, C3-006, S12-009 |
| `tool_input` | **opaque** | `tool_input`, same hooks | C1-005, C3-006 |
| `file_path` | string | `tool_input.file_path` of `Write`, `Edit`, `Read`, same hooks: the file a tool writes or reads | S13-008, S13-011, S13-014, C3-005 |
| `tool_response` | **opaque** | `tool_response` on `PostToolUse` | C1-011, C1-016 |
| `duration_ms` | integer | `duration_ms` on `PostToolUse`, `PostToolUseFailure` | C1-013, S12-009 |
| `error` | string | `error` on `PostToolUseFailure`, e.g. `Exit code 1` plus stderr | S12-009 |
| `is_interrupt` | boolean | `is_interrupt` on `PostToolUseFailure` | S12-009 `false` |
| `spawn_description`, `spawn_prompt`, `spawn_type` | string | `tool_input.description`, `.prompt`, `.subagent_type` on `PreToolUse` of `Agent` | C1-005, C2-006 |
| `spawn_model` | string | `tool_input.model` on `PreToolUse` of `Agent`: the alias the call sets (`haiku`, `sonnet`, …), not a full model ID. Absent when the subagent inherits its model (from its agent definition or the orchestrator); never filled with a default | S16-008 `haiku`; absent S16-009 |
| `spawn_background` | boolean | `tool_input.run_in_background` on `PreToolUse` of `Agent` | C1-005 `false`; absent C2-006 |
| `spawned_agent` | non-empty string | `tool_response.agentId` on `PostToolUse` of `Agent`; equals the subagent's core `agent` | C1-016, C2-008 |
| `spawned_async` | boolean | `tool_response.isAsync` on `PostToolUse` of `Agent` | C2-008 `true` |
| `spawned_model` | string | `tool_response.resolvedModel` on `PostToolUse` of `Agent`: the full model ID the subagent runs with, also when inherited; the only place an inherited model shows | S16-012 `claude-haiku-4-5-20251001` (alias `haiku`), S16-011 `claude-sonnet-5-5` (inherited); C1-016, C2-008, S15-010 |
| `notification_message`, `notification_type` | string | `message`, `notification_type` on `Notification` | C3-007 |
| `agent_transcript_path` | string | `agent_transcript_path` on `SubagentStop` | C1-015 |
| `parent_tool_use_id` | non-empty string | `parent_tool_use_id` on `SubagentStart`/`SubagentStop`; **documented, not sent by 2.1.285** | – |
| `last_assistant_message` | string | `last_assistant_message` on `Stop`, `SubagentStop` | C1-015, C1-020; absent C2-027 |
| `background_tasks` | array, **opaque** entries | `background_tasks` on `Stop`, `SubagentStop` | C2-014, C2-020 |
| `background_agents` | array of non-empty strings | `id` of every `background_tasks` entry with `type: subagent`, same hooks: the core `agent` of each background subagent still running. `[]` when none runs; absent when `background_tasks` is | S6a-013 (a `shell` entry left out), S15-013, S15-018 `[]` |
| `compact_trigger` | string | `trigger` on `PreCompact`, `PostCompact` | C2-029, C2-033 |
| `compact_summary` | string | `compact_summary` on `PostCompact` | C2-033 |
| `from_model`, `to_model` | string | `from_model`, `to_model` on `PostModelSwitch` | C2-030 |

Left in `payload` because no app uses them today: `scratchpad_dir`, `InstructionsLoaded`'s and `ConfigChange`'s details, `permission_suggestions`, `PostToolBatch`'s `tool_calls`, `session_crons`, `stop_hook_active`, `custom_instructions`, and `PostModelSwitch`'s cost and cache keys. Adding one later is a mapping change (§6).

`source` has three meanings in Claude Code's payloads; only `SessionStart`'s is a target field, as `start_source`.

### 3.3 Correlation rules (Claude Code)

- **Turns.** A root turn is identified by `prompt_id` on root events: `Stop` carries the `prompt_id` of the `UserPromptSubmit` it completes (C1-004/020, C2-005/014, C2-021/022, C2-024/026, C3-004/010). Closing is sticky. A user interrupt sends no event ("Stop: not on user interrupt", `docs/events/claude-code.md`; S2, S3): the session status file shows it (§12), otherwise apps need a timeout.
- **`prompt_id` inside a subagent is the orchestrator's current prompt**, not a subagent turn. A background subagent's tool carries the first prompt (C2-015) while its `agent.stop` carries a later one (C2-023). Never key subagent state by it.
- **Subagents.** `agent.stop` finishes a subagent; this is sticky (contract §6). Internal agents have `agent_type: ""` and stop without a start (C2-025, C2-027, C2-031); their `agent_transcript_path` may not exist.
- **Tool result.** Block `kind` `tool.post` means success, `tool.failure` failure (a nonzero exit, S12-009, with `error`); both are core `tool.post` and close the call by `tool_call`. A tool interrupted by Esc sent neither (S3-008 has no post).
- **Permissions.** Match a `permission.request` to the tool call with equal (`session`, `agent`, `prompt_id`, `tool_name`, `tool_input`). In C3-005/006 `tool_input` is identical. A `notification` with `notification_type: permission_prompt` follows about 6 s later (C3-007).
- **Subagent ↔ `Agent` call** (core `tool: spawn_agent`):
  1. `parent_tool_use_id` on `agent.start`/`agent.stop`, once Claude Code sends it, is the `tool_call` of the spawning call.
  2. Otherwise `toolUseId` in `<transcript_path without .jsonl>/subagents/agent-<agent>.meta.json`. That is a side file, so it is app work (contract §6 step 2).
  3. `spawned_agent` on the `Agent` post equals the subagent's `agent`. Background launches have `spawned_async: true` and post right after the launch (C2-008); foreground ones post only after the subagent stopped (C1-016 after C1-015).
  The parent of a subagent is the core `agent` of its `Agent` call (absent: the root). Never assign by order.
- **Background agents.** A `turn.start` whose `prompt` starts with `<task-notification>` (C2-021, C2-024, S6a-023) or `<agent-message ` (S6-025, S6-034; the subagent called the tool `SubagentHandback` first, S6-023) carries a background agent's result, not a user prompt. In 2.1.287 interactive `Agent` calls without `run_in_background` were launched async (S6-010, S6-017, S6a-010). `background_tasks` is a snapshot of running background agents; observed entries have `id` (= `agent`), `type` (`subagent`), `status`, `description`, `agent_type` (C2-014), or `type: shell` with `command` instead of `agent_type` (S6a-020); `status` was always `running`. `background_agents` lists the subagents' IDs.
- **Stopped background agents.** A background agent stopped by the user (S15: Ctrl+X Ctrl+K) sends **no `agent.stop`**, and its running tool no `tool.post` (S15-012). It is only missing from the next snapshot: S15-013 has it in `background_agents`, S15-018 has `[]`. Rules for apps:
  - Only background agents appear in the snapshot (`spawned_async: true` on their `Agent` post); a foreground subagent is never in it (C1-015). Never end one by its absence.
  - A background agent missing from the `background_agents` of a root `turn.stop` or an `agent.stop` of the same `session` has ended, if that event's envelope `ts` is later than the one of the agent's `Agent` post (same second: keep it open; `ts` has seconds and async hooks are written late). Arrival order is only a hint (contract §6).
  - At its own `agent.stop` an agent is still listed (C2-020, S6-027, S6a-021); the `agent.stop` itself ends it, and closing is sticky.
  - 2.1.288 also starts a turn whose `prompt` is `Background agent "<description>" was stopped by the user.` (S15-017). It names the `Agent` call's `description`, not the agent, so don't match by it.
- **Session model.** No hook names the model of every session (S17, S18; nor do the session status file, §12, or the `CLAUDE_*` variables in the hook's environment). What there is: `model` on `session.start` (interactive `startup`, `compact`) and `to_model` on `model.change` (`/model`, also automatic switches). Rules for apps:
  - The model is a property of the `claude` process (envelope `pid`), not of the session: it holds until the next `model.change` of that process.
  - **`clear` keeps it.** `/clear` ends the session and starts a new one in the same process: `session.end` with `end_reason: clear` (S17-014) and `session.start` with `start_source: clear` (S17-015) of the new `session`, same `pid`, without `model`. The new session runs with the process's current model, including an earlier `/model` (S17: `/model sonnet` at S17-011, the first answer after `/clear` came from `claude-sonnet-5-5` according to the transcript). Apps carry the last known model of that `pid` over to the new session. Match by `pid` and `end_reason`/`start_source`, not by order: both come within milliseconds and may arrive either way round.
  - **`resume` doesn't.** `--continue`/`--resume` starts a new process whose model comes from its own flags and settings, not from the resumed session (S18: S17's session last ran on Sonnet; resumed with `--model haiku`, it answered with `claude-haiku-4-5-20251001`, and S18-003 has no `model`). Never take the model from earlier events of that `session`. It stays unknown until a `model.change` of the new process.
  - Headless sessions name no model at all (C1-001, S9-004).
  - Subagents name their own model (`spawn_model`, `spawned_model`); it is never the session's.
- **Session end.** `session.end` is sticky. After a crash it may be missing; the envelope `pid` is the `claude` process (contract §6).

## 4. Codex (`codex`)

### 4.1 Kinds

| Hook | Block `kind` | Core `kind` | Observed |
|---|---|---|---|
| `SessionStart` | `session.start` | `session.start` | X1-001, X2-014, X8-001 |
| `UserPromptSubmit` | `turn.start` | `turn.start` | X1-002 |
| `PreToolUse` | `tool.pre` | `tool.pre` | X1-003 |
| `PermissionRequest` | `permission.request` | `permission.request` | X2-004 |
| `PostToolUse` | `tool.post` | `tool.post` | X1-004 |
| `PreCompact` / `PostCompact` | `compact.start` / `compact.end` | same | X2-012 / X2-013 |
| `SubagentStart` | `agent.start` | `agent.start` | X1-009, X1-015 |
| `SubagentStop` | `agent.turn.stop` (one child turn ended) | `other` | X1-014, X1-019, X1-026 |
| `Stop` | `turn.stop` | `turn.stop` | X1-028 |
| `Interrupt` | `turn.interrupt` | `other` | X3-010, X4-003, X6-004 |
| anything else | `unknown` | `unknown` | – |

### 4.2 Fields, Codex 0.159.3

| Block field | Type | From the payload, on which hooks | Evidence |
|---|---|---|---|
| `kind` | string | `hook_event_name` via §4.1 | |
| `turn_id` | non-empty string | `turn_id`, every hook except `SessionStart`; child events carry the child's turn | X1-002, X1-009; absent X1-001 |
| `rollout_path` | string or null | **this thread's rollout**: `agent_transcript_path` on `SubagentStop`, else `transcript_path`; `null` when ephemeral | X1-001, X1-009, X1-014, X9-001 |
| `parent_rollout_path` | string or null | `transcript_path` on `SubagentStop` (the parent's rollout) | X1-014 |
| `model` | string | `model`, every hook, per thread | X1-007 vs. X1-009 |
| `permission_mode` | string | `permission_mode`, all but compaction | X1-001; absent X2-012 |
| `agent_type` | string | `agent_type`, child events | X1-009 |
| `start_source` | string | `source` on `SessionStart` | X1-001 `startup`, X2-014 `compact`, X8-001 `resume` |
| `prompt` | string | `prompt` on `UserPromptSubmit` | X1-002 |
| `tool_name` | string | `tool_name` on `PreToolUse`, `PostToolUse`, `PermissionRequest` | X1-003, X2-004 |
| `tool_input` | **opaque** | `tool_input`, same hooks; `PermissionRequest` adds `description` | X1-003, X2-004 |
| `command` | string | `tool_input.command` of `Bash`, same hooks | X1-003, X2-004 |
| `tool_response` | **opaque** | `tool_response` on `PostToolUse`; observed always a string, possibly empty, sometimes JSON-encoded | X1-004, X1-006, X1-008 |
| `spawn_name` | string | `tool_input.task_name` of `collaborationspawn_agent` on `PreToolUse`/`PostToolUse` | X1-007 `alpha` |
| `spawn_task` | string | `tool_response` of `collaborationspawn_agent` on `PostToolUse`, **parsed as JSON**, its `task_name`: a task path, not the child's `agent` | X1-008 `/root/alpha` |
| `compact_trigger` | string | `trigger` on `PreCompact`, `PostCompact` | X2-012, X2-013 |
| `last_assistant_message` | string | `last_assistant_message` on `Stop`, `SubagentStop` | X1-014, X1-028 |

Left in `payload`: `stop_hook_active`, and `tool_input.message` of spawns, which is an opaque encrypted blob (X1-007; replaced by a placeholder in the fixtures).

### 4.3 Correlation rules (Codex)

- **Turn key** = (`session`, `agent` or root, `turn_id`). `turn.start`, `tool.pre`, `permission.request` and `agent.start` make it active. Closing is sticky:
  - Root turns close with `turn.stop` or `turn.interrupt`; no `turn.stop` follows an interrupt (X3-010, X4-003, X5-003, X6-004, X7-004, X10-008).
  - Child turns close with `agent.turn.stop`. A child can be reused: it becomes active again under a new `turn_id` without a new `agent.start` (X1-014 closes `…221c…`, X1-024 opens `…804b…`, X1-026 closes it).
  - A late `tool.post` for a closed turn closes only its call (X6-009, after X6-008).
- **Tool result: unknown, always.** There is no outcome field. The failed `sh -c "exit 7"` has `tool_response: ""` (X1-006), exactly like successful calls (X1-022, X2-005). Exit codes exist only in the rollout.
- **Permissions.** Match a `permission.request` to the call with equal (`session`, `agent`, `turn_id`, `tool_name`, `command`), regardless of arrival order (before the pre: X2-008/009, X3-003/004; after: X2-003/004). Don't compare `tool_input` whole: the request adds `description`. Several candidates → leave it unmatched. A rejection ends the turn with `turn.interrupt` (X3-008…010). A remembered approval sends no request (X3-017).
- **Child ↔ spawn** (core `tool: spawn_agent`): the spawn's post has `spawn_task` (`/root/alpha`). No child event names its task path or spawning call (X1-009 … X1-026). The link needs the child rollout's first `session_meta` line (`payload.source.subagent.thread_spawn.agent_path`); the child's `rollout_path` points to that file (X1-009, `rollouts/session_meta.jsonl` of X1). That is app work. In ephemeral sessions (`rollout_path: null`, X9) children stay unassigned. The parent is the core `agent` of the spawning call (absent: the root). Never assign by order: X1-015 arrives after X1-014.
- **Session end.** There is no end event (`SessionEnd` is never subscribed). Apps infer inactivity from a timeout; the envelope `pid` can be a shared app-server (contract §6).

## 5. Mapping document format

One JSON file per source, `model/<source>.json`:

```json
{
  "format": 1,
  "revision": 1,
  "source": "codex",
  "block": "codex",
  "observed": ["0.159.3"],
  "core":   { "<core field>":  <field spec>, … },
  "fields": { "<block field>": <field spec>, … }
}
```

- `format`: the version of this format. An interpreter that doesn't know it applies nothing (every target field absent) and says so in its log.
- `revision`: an integer that increases with every change of the document (CI checks it on pull requests). It orders documents of one source: an app uses the higher revision of `$ROOT/model/<source>.json` and the copy it bundles (contract §12). It never changes how a document is applied.
- `source`: the envelope `source` the document is for. `block`: the name of the block in the result.
- `document` (optional): what the document applies to. `hook-event` (the default): the `payload` of an event file. `session-status`: a session status file (§12). Interpreters apply both the same way; it tells apps which files to feed it and which result schema holds.
- `observed`: the agent versions the mapping was checked against. Informational only; interpreters never switch on it.
- `core`, `fields`: one **field spec** per target field.

The result of applying a document to a payload is `{ <core fields>, "<block>": { <block fields> } }`. A field whose spec yields no value is left out. The block is always present. Hook-event documents always yield the core `kind` and the block `kind` (both have a `default`); session-status documents have no `kind`.

### 5.1 Field specs and rules

A field spec is one **rule** or an ordered list of rules. The first rule whose `when` holds is the one evaluated; its result, even "no value", is the field's result. If no rule's `when` holds, the field is absent. (Without this, `rollout_path` on a `SubagentStop` missing `agent_transcript_path` would wrongly fall through to the parent's path.)

A rule is an object with these keys, evaluated in this order:

| Key | Value | Effect |
|---|---|---|
| `when` | list of conditions | The rule applies only if every condition holds. A condition is `{ "path": <pointer>, "in": [<strings>] }`: it holds if the value at the pointer is a string equal to one of the listed strings. Absent `when` always holds. |
| `path` | JSON Pointer ([RFC 6901](https://www.rfc-editor.org/rfc/rfc6901)), or a list of them | The value at the first pointer that exists in the payload. A key holding `null` exists. None exists → no value. |
| `parse` | `"json"` | The value must be a string; it is parsed as JSON. Not a string or not valid JSON → no value. |
| `pick` | JSON Pointer | Applied to the parsed value (only together with `parse`). Missing → no value. |
| `each` | a field spec | The value must be an array, else no value. The spec is applied to every element as if the element were the payload (its pointers start at the element). Elements whose spec yields no value are left out; the value is the array of the others, in order. An empty array stays empty. |
| `map` | object of string → value | The value must be a string listed as a key; it is replaced by the listed value. Otherwise no value. |
| `type` | a type name, or a list of them (any matches) | The value must have this type, else no value. Names: `string`, `id` (non-empty string), `integer`, `number`, `boolean`, `object`, `array`, `null`, `any` (the default). |
| `default` | any JSON value | Used when the steps above yield no value (the rule's `when` held). |
| `note` | string | Ignored; documentation. |

**Interpreter rules:**

- A rule with any other key yields no value (the field is absent, it is never guessed). Likewise a condition with any other key doesn't hold. New operations are added as new keys, so an older interpreter leaves those fields absent instead of reading them wrongly. Only changing the meaning of an existing key bumps `format`.
- Values are copied unchanged: numbers as parsed, `null` kept, opaque structures whole.
- The interpreter never fails on a payload. Malformed input yields absent fields, `kind` falls back to its `default` (`unknown`).

### 5.2 Examples

```json
"session": { "path": "/session_id", "type": "id" }

"kind": { "path": "/hook_event_name", "map": { "SubagentStop": "agent.turn.stop", "Stop": "turn.stop" }, "default": "unknown" }

"spawn_task": {
  "when": [ { "path": "/hook_event_name", "in": ["PostToolUse"] },
            { "path": "/tool_name", "in": ["collaborationspawn_agent"] } ],
  "path": "/tool_response", "parse": "json", "pick": "/task_name", "type": "string" }

"rollout_path": [
  { "when": [ { "path": "/hook_event_name", "in": ["SubagentStop"] } ],
    "path": "/agent_transcript_path", "type": ["string", "null"] },
  { "path": "/transcript_path", "type": ["string", "null"] } ]

"background_agents": {
  "when": [ { "path": "/hook_event_name", "in": ["Stop", "SubagentStop"] } ],
  "path": "/background_tasks",
  "each": { "when": [ { "path": "/type", "in": ["subagent"] } ], "path": "/id", "type": "id" } }
```

`each` both projects and filters: the inner `when` drops the `shell` entries, `path` picks each remaining entry's `id`. `[{"id":"a1","type":"subagent",…},{"id":"b2","type":"shell",…}]` yields `["a1"]`; `[]` yields `[]`; a missing `background_tasks` leaves the field absent.

A drift such as a key renamed from `agent_transcript_path` to `child_transcript_path` is absorbed by `"path": ["/child_transcript_path", "/agent_transcript_path"]`: new payloads use the new key, old event files still resolve the old one.

## 6. Drift and versioning

When an agent changes:

1. Capture the new version into `fixtures/<source>/<version>/` and write its golden files (§7).
2. Change the mapping: add a fallback path, a table entry, a field, or a rule. Never replace a path that older captures still need; all fixtures of all versions must keep producing their golden files.
3. Increase `revision`, add the version to `observed` and release.

Compatible changes, which apps must tolerate: new target fields, new block kinds, new table entries, new core tool categories, new core kinds for events that gain a shared meaning. Apps ignore unknown fields, treat unknown block kinds like `unknown`, and unknown core `tool` values like `other`. Changing a target field's meaning or type, or removing it, is a breaking change of the target model and needs a new target field name.

## 7. Golden files

**Layout:** next to each run's `events/` there is an `expected/` folder with one file per event, using the same file name:

```
fixtures/<source>/<version>/<run>/
├── events/NNN-<hook_event_name>.json     # raw payload, byte for byte (the reference)
├── expected/NNN-<hook_event_name>.json   # model/<source>.json applied to it
├── status/NNN-status.json                # session status file, where captured (§12)
└── status-expected/NNN-status.json       # model/<source>-session.json applied to it
```

- Content: the result object (§5), pretty-printed with two spaces, LF line endings and a trailing newline. Comparison is semantic (as JSON values).
- All 394 fixture events (286 Claude Code, 108 Codex) and all 92 status snapshots (Claude Code 2.1.287 to 2.1.289) have one. A new capture adds its `expected/` files in the same PR; `python3 tools/model/apply.py model/<source>.json < events/F` prints a first version to review by hand.
- The existing globs (`fixtures/*/*/*/events/*.json` in CI and `tools/e2e/check.sh`) don't see `expected/`.

**CI check** (`tests/model.test.py`): for every `events/F`, apply `model/<source>.json` with the reference interpreter `tools/model/apply.py` and compare with `expected/F`; fail if an `events/` file has no `expected/` file or the other way round. Likewise `status/F` with `model/<source>-session.json` and `status-expected/F`. The same test covers each rule of §5.1 and checks that every adapter ships its own mapping unchanged. CI also validates the mapping documents and golden files against their schemas (§11). The reference interpreter runs only in CI and tests, never in the hook. The golden files are also the test suite for each app's interpreter: both apps run their own interpreter over the same fixtures and mappings.

## 8. What the mapping provides and what stays app work

| | Provided by the mapping | App work |
|---|---|---|
| Root/subagent attribution | core `agent` | – |
| Tool pairing | core `tool_call` | pairing across files |
| Permission ↔ call | the match fields (§3.3, §4.3) | matching, ambiguity |
| Subagent ↔ spawn, Claude Code | `spawned_agent` on the `Agent` post; `parent_tool_use_id` once sent | earlier link via `meta.json` |
| Child ↔ spawn, Codex | `spawn_task`, child `rollout_path` | reading `session_meta` from the rollout |
| Turn/agent state | block kinds and turn IDs | sticky state, timeouts |
| Liveness | Claude Code `session.end`; session status `state` (§12) | `pid` checks, file presence, Codex timeouts |
| Working, waiting, idle (incl. user interrupts) | Claude Code session status `state`, `waiting_for` (§12) | combining with the hook state |

**What the operations can't express**, and doesn't need to:

- Comparisons between fields or events (pairing, matching, sticky state). By design: the mapping is stateless.
- String tests other than equality. "`prompt` starts with `<task-notification>` or `<agent-message `" (C2-021, S6-025) stays an app rule on `prompt`.
- Anything in side files (`meta.json`, rollouts).

Every target field in §2–§4 is expressed with the operations of §5.1; none needed code.

## 9. Review from both apps' view

Checked against today's logic in The Collective (`ClaudeCodeAdapter.swift`) and Unimatrix Zero (`docs/decisions.md` §29):

| Need | Target fields |
|---|---|
| Session start, `cwd`, end | core `session.start`, `cwd`; Claude Code `session.end`, `end_reason` |
| Session model | Claude Code `model`, `to_model`, carried over per `pid` on `clear` (§3.3 "Session model") |
| Prompt text, notification prompts | block `prompt`; Claude Code `<task-notification>` / `<agent-message ` prefix |
| Tool activity and a one-line detail | core `tool.pre`, `tool`; block `tool_name`, `tool_input` (`command`, `file_path`, …), Codex `command` |
| Tool pairing, late pre | core `tool_call` |
| Subagent tree, title, prompt, background, model | core `agent`; Claude Code `spawn_*`, `spawned_agent`, `spawned_async`, `spawned_model`; Codex `spawn_name`, `spawn_task` |
| Internal agents | Claude Code `agent_type: ""` |
| Waiting for the user | core `permission.request`; Claude Code `notification_type` |
| Done | core `turn.stop` plus open agents; Claude Code `background_agents` (also ends agents stopped by the user, which send no `agent.stop`) |
| Touched files | Claude Code `file_path` of `Write`/`Edit` (S13-008, S13-011); Codex writes through the shell without a path (X2-003) |
| Transcript paths | Claude Code `transcript_path`, `agent_transcript_path`; Codex `rollout_path`, `parent_rollout_path` |

Anything else an app wants is still in `payload`; reading it there couples that app to the agent's format again, so the better path is to ask for a target field.

## 10. Open questions and weak spots

**Claude Code**
- No user-interrupt event (the session status file covers it, §12), and no turn ID inside subagents (`prompt_id` is the orchestrator's).
- `parent_tool_use_id` is unobserved; its target field is defined ahead of the capture.
- MCP tools, `NotebookEdit`, the older `Task` name, `StopFailure` and ten more hooks are unobserved. The 2.1.287 captures cover `Write`/`Edit`/`Read`/`Grep`/`Glob` (S13) and `PostToolUseFailure` (S12). Their drift against 2.1.285 (`effort`, `prompt_id` on `InstructionsLoaded`, cache keys on `SessionStart`, `permission_suggestions` going missing) touches no target field.
- The session's model is missing after `/clear`, on `resume` and in headless sessions (S17, S18, C1, S9); apps carry it over on `clear` only (§3.3).
- Subagent resume ("the same task-id may notify more than once", C2-021) is unobserved.
- A background agent stopped by the user has no end event; only its absence from `background_agents` shows it (S15). Stopping a single agent from the task list, rather than all with Ctrl+X Ctrl+K, is unobserved.

**Codex**
- Child ↔ spawn needs the rollout, and is impossible in ephemeral sessions. Nested spawning and reuse across resume are unobserved.
- There is no tool outcome at all.
- A child announces only its first turn.
- There is no session end and no background snapshot.
- Code-mode and MCP tool names are unobserved.

**Both**
- `parse: "json"` and `each` (projecting array elements) are the only transforms. If a future payload needs another one (say, splitting a string), it is a new rule key, and older interpreters leave that field absent until they learn it.
- The core is deliberately small. A field moves into the core only once both sources show the same meaning in a capture.

## 11. JSON Schemas

- `schema/<source>/result.v1.json` ([Claude Code](../schema/claude-code/result.v1.json), `$id` `urn:subspace:result:claude-code:v1`; [Codex](../schema/codex/result.v1.json), `urn:subspace:result:codex:v1`): the result of applying that source's mapping: the core (§2), identical in both (`tests/model.test.py` checks it), plus that source's block. Blocks are closed, so a mapping can't produce a field the target model doesn't define; adding a target field ships mapping and schema together.
- [`schema/claude-code/session-status.v1.json`](../schema/claude-code/session-status.v1.json) (`$id` `urn:subspace:session-status:claude-code:v1`): the result of applying a session-status mapping (§12), closed like the result schema.
- [`schema/mapping.v1.json`](../schema/mapping.v1.json) (`$id` `urn:subspace:mapping:v1`): a mapping document. It is closed for this repository's own documents, so CI catches typos. Interpreters in the apps still follow §5.1 (unknown keys → field absent), so a newer document with new operations degrades instead of failing.

`schema/*.json` (envelope, mapping) ship in every adapter, `schema/<source>/*.json` only in that source's adapter (`tools/sync.sh`); all land flat in `$ROOT/schema/`. A schema change thereby releases only the adapters it concerns.

## 12. Session status (Claude Code)

Claude Code keeps one **session status file** per running process, `<config dir>/sessions/<pid>.json` (contract §13). It is a side source: subspace never reads or writes it, it documents it and ships a mapping for it, [`model/claude-code-session.json`](../model/claude-code-session.json) (`document: session-status`). Apps apply it to the file's content exactly like a hook mapping to a payload. Evidence: the status snapshots of `fixtures/claude-code/2.1.287/` (S1–S9).

### 12.1 Fields

| Field | Type | From the file | Evidence |
|---|---|---|---|
| core `session` | non-empty string | `sessionId`; equals the hooks' `session_id`. Can change within one file (S7-001/002) | S1-001 |
| core `cwd` | string | `cwd` | S1-001 |
| core `state` | `working`, `waiting` or `idle` | `status` via a table: `busy` and `shell` → `working`, `waiting` → `waiting`, `idle` → `idle`. Absent before the first `status` (S1-001) and for an unknown value | S1-003, S4-008, S6a-025 |
| `status` | string | `status`, raw; any value, also unknown ones | S1-003 |
| `status_at` | integer (Unix ms) | `statusUpdatedAt`: when `status` last changed | S1-003 |
| `waiting_for` | `permission`, `input` or `dialog` | `waitingFor` via a table (`permission prompt`, `input needed`, `dialog open`), only while `status` is `waiting`; absent for an unknown value | S4-008, S4-027, S6a-026 |
| `waiting_text` | string | `waitingFor`, raw, only while `status` is `waiting` | S4-008 |
| `pid` | integer | `pid`: the `claude` process, equals the file name and the hooks' envelope `pid` | S1-001 |
| `process_kind` | string | `kind`: `interactive`, also for `claude -p` (S9-001); `bg` for background sessions (outside the fixtures) | S1-001 |
| `entrypoint` | string | `entrypoint`: `cli`, `sdk-cli` for `claude -p` | S1-001, S9-001 |
| `name`, `version` | string | `name` (display name), `version` (Claude Code version) | S1-001 |
| `started_at`, `updated_at` | integer (Unix ms) | `startedAt`, `updatedAt` (any change of the file, not only `status`) | S1-001 |

Left in the file: `procStart`, `peerProtocol`, `peerFeatures`, `pidDomain`, `messagingSocketPath`, `nameSource`, `nameSince`, `jobId`, `parkedJobId`.

### 12.2 Meaning of `state`

- `working`: a turn runs, including tools, `!` shell commands (S5-006) and background subagents (S6: `working` across two `turn.stop`s until the last hand-back turn ended). `shell` (S6a-025) means no turn but a background shell still running; it maps to `working` too, the raw value stays in `status`.
- `waiting`: the session needs the user: a permission dialog (S4-008), a question (`AskUserQuestion`, S4-027), a dialog such as the exit confirmation (S6a-026). The hooks show the first two as well (`permission.request`, S4-010, S4-028), the dialog only here.
- `idle`: no turn runs. Reached after a normal end and, **without any hook event**, after Esc or Ctrl-C mid-turn (S2-008, S2-011) or mid-tool (S3-009) and after a rejected permission (S4-023).

### 12.3 Rules

- **Key by `session`, never by `pid`.** A process can carry another session over time (`--continue` S7-001/002; `/clear` S17-012/013; `claude bg-spare` processes take on new sessions).
- **Newer wins.** Compare `status_at` with the hook events' times; the newer source says whether the session is working. A hook can't undo an `idle` that is newer than it.
- **Deleted file = process ended.** Deleted on `/exit` and at the end of `claude -p`. After a crash (`kill -9`) it stays until the next `claude` process starts (S8, S6a), so a present file whose `pid` is not alive is stale.
- **Missing, unparseable or `state` absent → unknown.** Fall back to the hooks and a timeout. Never guess from an unknown `status`.
