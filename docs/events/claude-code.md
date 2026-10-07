# Claude Code hook events: what subspace subscribes to

Based on Claude Code 2.1.285. Source: [hooks reference](https://code.claude.com/docs/en/hooks). Feeds contract §6, `hooks.json` and the capture tool.

**Basis for every entry:** subspace registers only `command` hooks with `async: true`, always exits 0 and writes nothing to stdout or stderr. Per the reference:

- Exit 0 with no output means "no decision"; the normal flow continues ("The hook can deny the call, but staying silent doesn't approve it.").
- Async hooks can't steer anyway: "response fields like `decision`, `permissionDecision`, and `continue` have no effect".

An event is subscribed only if **registering it alone** changes nothing about Claude Code's behavior.

## Subscribe

| Event | Matcher | What it tells us (examples) | Note |
|---|---|---|---|
| `SessionStart` | – | session started or resumed, `source`, `model` only on an interactive `startup` and on `compact` (not on `clear`, `resume`, `claude -p`; contract §6) | Sync would delay Claude's first response; async doesn't. |
| `SessionEnd` | – | session ended, `reason` | All SessionEnd hooks share a 1.5 s budget. Async delivery after `/exit` and Ctrl-C is covered by the captures. |
| `Setup` | – | only with `--init`/`--init-only`/`--maintenance` | Rare, harmless. |
| `InstructionsLoaded` | – | which `CLAUDE.md`/rules were loaded | "runs asynchronously for observability purposes". |
| `UserPromptSubmit` | – | the user's prompt | **stdout would become context for Claude**, so nothing may be printed. |
| `UserPromptExpansion` | – | slash command or skill invoked directly | As above: stdout would become context for Claude. |
| `PreToolUse` | `*` | tool starts; for `Agent`, a subagent starts with type, description, prompt | |
| `PermissionRequest` | `*` | **waiting for approval, immediately** | `Notification`/`permission_prompt` only fires after about 6 s. Without a decision the normal dialog runs. Has no `tool_use_id`. `permission_suggestions` is optional: 2.1.286 omits it when there are none. |
| `PermissionDenied` | `*` | auto mode denied a call | Auto mode only. |
| `PostToolUse` | `*` | tool finished, `tool_response` | |
| `PostToolUseFailure` | `*` | tool failed | |
| `PostToolBatch` | – | parallel batch complete | Can only block via exit 2 or JSON. |
| `Notification` | – | `permission_prompt`, `idle_prompt`, `agent_needs_input`, `agent_completed`, quota … | Exit code is ignored. |
| `SubagentStart` | – | subagent starts: `agent_id`, `agent_type` | Also fires on resume and per message of an in-process teammate. The reference also lists `description` and `parent_tool_use_id` (the spawning `Agent` call); 2.1.285 sends neither (contract §6). |
| `SubagentStop` | – | subagent finished, `last_assistant_message`, `agent_transcript_path` | The reference lists `parent_tool_use_id`; 2.1.285 doesn't send it. |
| `TaskCreated` / `TaskCompleted` | – | task list and agent teams | No matchers. |
| `TeammateIdle` | – | agent team teammate goes idle | |
| `Stop` | – | response finished, `last_assistant_message`, `background_tasks` | Not on user interrupt. |
| `StopFailure` | – | turn ended with an API error, `error` | Output and exit code are ignored. |
| `PreCompact` / `PostCompact` | – | context is being / was compacted | |
| `PostModelSwitch` | – | model changed (`from_model`, `to_model`), including automatic changes | stdout would become context for Claude. |
| `ConfigChange` | – | settings or skills changed | |
| `CwdChanged` | – | working directory changed | No effect without `watchPaths` in the output. |
| `DirectoryAdded` | – | `/add-dir` | "Claude Code doesn't wait for the hook". |
| `Elicitation` | – | an MCP server asks the user for input | Without `hookSpecificOutput` the normal dialog is shown. |
| `ElicitationResult` | – | the user answered an elicitation | Without output the answer is unchanged. |

## Never subscribe

| Event | Why |
|---|---|
| `WorktreeCreate` | "Configuring a WorktreeCreate hook replaces that default git behavior". The hook must print the path, otherwise creation fails. |
| `WorktreeRemove` | "Hook exits 0: the worktree counts as removed. Claude Code reads nothing else from the hook, so make sure your hook deleted the directory." A registered hook takes over removal, so worktrees would be left behind. |
| `PreModelSwitch` | Runs sequentially before the switch; "a hook canceled at its timeout blocks the model switch". `PostModelSwitch` is enough for observing. |

## Skipped for other reasons

| Event | Why |
|---|---|
| `MessageDisplay` | "Claude Code holds each batch until your hook returns". Whether `async` lifts this is undocumented. It also fires per streamed text batch, multiplying the volume. The text is available in `Stop`/`SubagentStop` (`last_assistant_message`) and in the transcript. Reconsider only after a dedicated test. |
| `FileChanged` | The matcher defines which files Claude watches (literal file names in the working directory). Without a matcher nothing is watched; with one, subspace would extend Claude's behavior. No gain over `PostToolUse`. |

## Consequences for other issues

- **No output, truly none:** On `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart` and `PostModelSwitch`, Claude Code adds plain-text stdout **as context for Claude**. A nonzero exit code shows a visible `hook error` on most events. `spool.sh` therefore sends everything to `/dev/null` and always exits 0.
- **Non-interactive mode:** "In non-interactive mode with the `-p` flag, Claude Code kills any async hook still running at teardown". A capture run with `claude -p` can lose late events such as `Stop` or `SessionEnd`, so the capture also needs an interactive run.
- **async is documented for `command` hooks only**; the reference names no per-event restriction. The captures show every subscribed event arriving async.
- **Correlation:** `PermissionRequest` has no `tool_use_id`. Apps match it to the preceding `PreToolUse` via `session_id`/`agent_id` plus `tool_name`/`tool_input` (order per the reference: `PreToolUse` → `PermissionRequest` → `PostToolUse`).

## Observed

The 2.1.285 capture (`fixtures/claude-code/2.1.285/`) saw 16 of the 28 subscribed events with async hooks, including `SessionEnd` after `/exit` and Ctrl-C. Not yet observed: `Setup`, `UserPromptExpansion`, `PermissionDenied`, `PostToolUseFailure`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `StopFailure`, `CwdChanged`, `DirectoryAdded`, `Elicitation`, `ElicitationResult`.
