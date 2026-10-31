# Fixtures: Claude Code 2.1.316

Real hook payloads and session status files, recorded on 2026-10-31 on macOS with `tools/hook-capture/claude-code/drive-session-runs.py S19`. Layout, numbering and `timeline.jsonl` as in [`../2.1.287/README.md`](../2.1.287/README.md). Payloads and status files are unchanged, anonymized as described in [`../../README.md`](../../README.md#anonymization). Transcripts are not included.

## Runs

| Run | What happened | Status sequence |
|---|---|---|
| `19-ask-user-question` | Haiku, `--permission-mode default`. Three `AskUserQuestion` calls, one per prompt: (1) two questions, a `multiSelect` one answered with two options and a single-choice one answered with free text ("Type something"), submitted on the review screen after 15 s; (2) one question whose options have a `preview`, answered with a note on the chosen option within 6 s; (3) one question dismissed with Esc after 15 s. Then one prompt without tools, `/exit` | – idle busy **waiting** (`input needed`) busy idle busy **waiting** busy idle busy **waiting** **idle** busy idle busy, deleted |

– = the first snapshot, written before `status` is set.

## Findings

- **Questions** (`PreToolUse` 008/020/031, `PermissionRequest` 010/022/033): `tool_input.questions` as in 2.1.287 (`question`, `header`, `options` with `label` and `description`, `multiSelect`); options can also carry `preview` (020). `PermissionRequest` fires for every call, `Notification` (`permission_prompt`) only after about 6 s (011, 034; none for call 2, answered sooner). The status file shows `waiting` / `input needed` (009, 021, 032).
- **Answers** (`PostToolUse` 013, 024): `tool_input` and `tool_response` are both `{questions, answers, annotations}`, identical. `answers` is keyed by the question text:
  - a `multiSelect` answer is **one string**, the chosen labels joined by `", "`: `"apple, cherry"` (013; picked in option order, so whether the order follows the options or the clicks is open);
  - a free-text answer is the typed text: `"a parrot"` (013), with no marker that it is not one of the labels;
  - a single choice is its label: `"List"` (024).
- **Notes** (024): `annotations` is keyed by the question text as well, `{"preview": <the chosen option's preview>, "notes": "more compact please"}`. Without notes it is `{}` (013). The note key `n` is offered only for options with a `preview`.
- **Dismissed with Esc** (call 3): **no hook event at all**: no `PostToolUse`, no `PostToolUseFailure`, no `PostToolBatch`, no `Stop`. Only the status file goes from `waiting` to `idle` (035), as for an interrupt (2.1.287 S2, S3). The next prompt starts a normal turn (037, 039).
- `PostToolBatch` (014, 025) has a prose `tool_response` ("Your questions have been answered: …"), as in 2.1.287.
- After each `Stop` an internal agent stops (`SubagentStop` with `agent_type: ""`, 017, 028, 040), as in 2.1.285 C2-025.
- **Drift against 2.1.289** (no target field affected): `PermissionRequest` has `effort` and no `permission_suggestions`; the status file has a new key `asksForConvertedSkills`. `SessionStart` (`startup`) has `model: claude-haiku-5-5`.
