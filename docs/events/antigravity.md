# Antigravity hook events: what subspace subscribes to

Based on Antigravity CLI `agy 1.5.16` / `1.5.17`, Antigravity desktop App `2.35.1` (`Antigravity.app`), CLI help (`agy --help`, `agy plugin --help`, `agy plugin validate --help`), local `agy plugin validate --strict` checks, and the official Antigravity customization, hooks and plugins documentation.

**Evidence:** macOS captures recorded on 2026-11-25 with `tools/hook-capture/antigravity/` and curated in [`fixtures/antigravity/1.5.17/`](../../fixtures/antigravity/1.5.17/), plus a disposable installed-plugin probe (`agy plugin install`/`list --json`/`uninstall`). Where documentation and captures differ, captures win.

## Classification

Antigravity defines **six** lifecycle events (`SessionStart`, `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`).

**Basis:** a local `command` handler that writes nothing to stdout or stderr and exits 0.

**Synchronous runtime:** Antigravity supports only `type: "command"` handlers (no HTTP or prompt hooks) and runs hooks **synchronously**, blocking the agent loop with no `async` execution mode (`docs/hooks.md`, "Current Limitations"). `core/spool.sh` stays fast enough to run synchronously (contract §1: "Sync must stay possible").

### Subscribe

Captures confirmed all six events work cleanly with empty stdout, empty stderr and exit 0 — zero stderr, zero hook warnings and no altered permission decisions:

| Event | Structure & matcher | Observe-only reasoning (capture-verified) |
|---|---|---|
| `SessionStart` | Flat handler array; no matcher | Silent exit 0 injects no steps and produces no warning. Fires once when a new conversation starts (in interactive CLI on the first prompt, not on TUI launch); does **not** fire on `--conversation` resume. Also fires for each subagent conversation. |
| `PreToolUse` | Grouped `{matcher, hooks}`; `"matcher": "*"` | **Verified non-steering:** although the reference marks `decision` as required, silent exit 0 acts as a pure abstain. In `auto` mode, auto-allowed tools ran without prompting; in `accept-edits` mode, `PreToolUse` fired before the permission prompt and the interactive `Run this command?` dialog still appeared normally (both Option 1 approve and Option 4 / `Esc` cancel behaved unchanged). |
| `PostToolUse` | Grouped `{matcher, hooks}`; `"matcher": "*"` | Runs after tool completion, including nonzero shell exits (`error: ""` on `sh -c "exit 7"`). Silent exit 0 produces no warning even though the reference says stdout expects `{}`. Does **not** fire on user-denied or `Esc`-interrupted tools. |
| `PreInvocation` | Flat handler array; no matcher | Fires before each model call (`invocationNum`, `initialNumSteps`). Silent exit 0 proceeds without injecting steps or terminating. |
| `PostInvocation` | Flat handler array; no matcher | Fires after each model/tool step round completes. Silent exit 0 neither forces continuation nor terminates. Does **not** fire when a tool is denied or interrupted mid-turn. |
| `Stop` | Flat handler array; no matcher | Fires when the execution loop ends (`executionNum`, `terminationReason`, `error`, `fullyIdle`, `continuationActive`). Silent exit 0 allows the stop cleanly with no warning. Does **not** fire on `Esc` interruption or permission denial (`No, cancel`) in `1.5.17`, even though the reference lists `USER_CANCELED`. |

### Not defined in Antigravity

Antigravity's six-event registry has no `SessionEnd`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUseFailure`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `Notification`, `Interrupt`, `PostModelSwitch`, `WorktreeCreate` or `WorktreeRemove`. Do not invent equivalents.

## Findings

### 1. Configuration, scopes, matching and working directory

Hooks are declared in a `hooks.json` object whose top-level keys are **named hook groups**, each mapping to event arrays and an optional `"enabled": false` toggle. Multiple named hooks across configs and plugins merge and execute sequentially.

- **Discovery locations:** workspace `.agents/hooks.json` (also `.agent/`, `_agents/`, `_agent/`, walking from the working directory up to the repository root), global `~/.gemini/config/hooks.json`, and bundled plugin `<plugin_dir>/hooks.json`.
- **Event structure:** `PreToolUse` and `PostToolUse` require grouped entries `[{"matcher": "*", "hooks": [...]}]`, matching tool names (`run_command`, `read_file`, `write_file`, `invoke_subagent`, `send_message`, `update_steps`, …). `SessionStart`, `PreInvocation`, `PostInvocation` and `Stop` take a flat array of handler objects directly.
- **Handler fields:** `type` (optional, default `"command"`), `command` (required; run via `sh -c` on Unix, `cmd /c` on Windows; `~` expanded), `timeout` (optional integer seconds, default `30`).
- **Observed hook working directory (`pwd`):** always **the directory containing `hooks.json`** — `.agents/` for workspace hooks (even when the agent runs in a nested workspace like `captures/project with spaces`, where `payload.cwd` carries that nested directory) and `<plugin_dir>` (`~/.gemini/config/plugins/<name>`) for installed plugins.

### 2. Input/output contract, camelCase payloads and `envelope.v1.json`

Hook commands receive one compact JSON object on **stdin** with **camelCase** keys (protojson encoding):

- **Common fields (all 6 events):** `artifactDirectoryPath`, `conversationId`, `cwd`, `hookEventName`, `lastUserInput`, `modelName`, `transcriptPath`, `workspacePaths`.
- **`PreToolUse`:** adds `stepIdx`, `toolCall` (`id`, `name`, `args`).
- **`PostToolUse`:** adds `stepIdx`, `toolCall` (`id`, `name`, `args`), `error` (always present as a string; `""` on normal completion **and** on `run_command` nonzero exit `7`; no `tool_response`/output field).
- **`PreInvocation` / `PostInvocation`:** adds `invocationNum`, `initialNumSteps`. Both `invocationNum` and `executionNum` reset to `0` on each new user prompt, subagent wakeup or resumed turn, while `stepIdx` and `initialNumSteps` continue increasing across the conversation.
- **`Stop`:** adds `continuationActive`, `error`, `executionNum`, `fullyIdle`, `terminationReason` (observed `NO_TOOL_CALL`).

**Silence verified:** empty stdout and stderr with exit 0 produced zero warnings, errors or behavioral changes across all six events in both CLI (`1.5.16`/`1.5.17`) and desktop App (`2.35.1`). No `{}` output is required, so `core/spool.sh` stays completely silent across every source.

**`envelope.v1.json` impact:** because payloads use `hookEventName` instead of `hook_event_name` and subspace keeps payloads byte for byte, `schema/envelope.v1.json` must allow `hookEventName` alongside `hook_event_name` when adding the Antigravity adapter.

### 3. Plugin packaging, `PLUGIN_DATA` and uninstall

Native Antigravity plugins are directories containing `plugin.json`, `.antigravity-plugin/plugin.json` or `.gemini-plugin/plugin.json`.

- **Manifest & root `hooks.json`:** `.antigravity-plugin/plugin.json` matches `core/spool.sh`'s existing `../.*-plugin/plugin.json` version lookup and release-please's `extra-files`. Native plugins **must** place `hooks.json` at the plugin root (`hooks/hooks.json` is never loaded and fails `agy plugin validate --strict` with `"never loaded: plugin hooks are read only from hooks.json at the plugin root"`). Verified with `agy plugin validate --strict --json`: `.antigravity-plugin/plugin.json` + root `hooks.json` exits 0 with `components.hooks: 1`.
- **Observed installed paths (CLI `agy 1.5.16`):**
  - `PLUGIN_ROOT` and hook `pwd`: `~/.gemini/config/plugins/<name>`
  - `PLUGIN_DATA`: `~/.gemini/antigravity-cli/plugin_data/<name>` (created `0755` by Antigravity)
  - `CLAUDE_PLUGIN_DATA`: **unset** — `core/spool.sh` needs a fallback from `CLAUDE_PLUGIN_DATA` to `PLUGIN_DATA`.
- **Surface-specific app data dir:** the desktop App (`2.35.1`) runs its `language_server` with `--app_data_dir antigravity` (writing transcripts under `~/.gemini/antigravity/brain/...`), whereas CLI uses `antigravity-cli/`. Installed-plugin `$PLUGIN_DATA` for App (`~/.gemini/antigravity/plugin_data/<name>`?) and IDE (`antigravity-ide/`) still needs an installed-plugin check.
- **Uninstall preserves `$PLUGIN_DATA`:** `agy plugin uninstall subspace-probe` removed `~/.gemini/config/plugins/subspace-probe` but left `~/.gemini/antigravity-cli/plugin_data/subspace-probe` intact (like Codex).
- **Detection (`agy plugin list --json`):** returns a JSON array of objects `{ "name", "enabled", "version", "source", "path", "hooks" }`.

### 4. Process model (`pid`), environment and terminal identifiers

- **Hook environment:** when run without inherited variables from a parent Antigravity session, CLI hooks see only `ANTIGRAVITY_CONVERSATION_ID` (plus `PLUGIN_ROOT`/`PLUGIN_DATA` for plugins); desktop App hooks see `AGY_REQUIRE_AUTHENTICATED_UI_BOOTSTRAP` and `ANTIGRAVITY_CONVERSATION_ID`.
- **CLI `pid`:** `$PPID` is the session's `agy` process directly (shared between a root conversation and its subagents in the same `agy` process).
- **Desktop App `pid`:** both App conversations (`c3c435ff`, `a0c7175e`) had the **exact same `$PPID`** — the single shared `/Applications/Antigravity.app/Contents/Resources/bin/language_server` process spawned by `Antigravity.app`. Apps therefore **must not** use `pid` as a per-session liveness check for Antigravity; use a timeout since the last event (like Codex).
- **Terminal identifiers (`terminal`):**
  - CLI in Warp inherited all five Warp/terminal variables (`TERM_PROGRAM`, `TERM_PROGRAM_VERSION`, `__CFBundleIdentifier`, `WARP_FOCUS_URL`, `WARP_TERMINAL_SESSION_UUID`).
  - Desktop App inherited `__CFBundleIdentifier=com.google.antigravity`, allowing consumer apps to bring `Antigravity.app` to the front using the existing contract §4 allowlist.

### 5. Subagents, permissions, interruption and transcripts

- **Subagents:** `invoke_subagent` starts a separate conversation with its own `conversationId` and `transcriptPath` in the same host process. That subagent fires all six hooks itself with `lastUserInput: ""` and **no parent ID field** in the hook payload.
  - When the parent finishes its launch turn while subagents still run, it emits `Stop` with `fullyIdle: false`; once subagent messages arrive, the parent wakes up (`PreInvocation`, `invocationNum: 0`) and ends with `Stop` (`fullyIdle: true`).
  - **Parent ↔ subagent correlation:** (1) the subagent's `send_message` tool call carries `toolCall.args.Recipient = <parent conversationId>` directly in the hook payload; (2) the parent transcript's `invoke_subagent` `GENERIC` step records the child's `conversationId`; (3) the child transcript's step 0 `SYSTEM_MESSAGE` records `sender=<parent conversationId>`.
- **Permissions and interruption:** `PreToolUse` fires **before** the interactive permission dialog. Approving (Option 1) proceeds to `PostToolUse` → `PostInvocation` → `Stop`. Denying (Option 4 `No, cancel` or `Esc`) or interrupting a running tool (`sleep 30` with `Esc`) emits **no `PostToolUse`, no `PostInvocation` and no `Stop`**. On Option 4 denial, the transcript records a `GENERIC` step with `status: "ERROR"` and `error: "permission check failed ... user denied permission to run command:"`.
- **Model and effort:** `modelName` is present on every hook payload as a concrete model identifier that encodes effort where applicable (observed `gemini-3.8-flash-low`, `gemini-4-neon-high`).
- **Transcripts (`transcriptPath`):** `~/.gemini/<app_data_dir>/brain/<conversationId>/.system_generated/logs/transcript_full.jsonl` (identical JSONL format across CLI and App). Records include `USER_INPUT`, `SYSTEM_MESSAGE`, `PLANNER_RESPONSE` (`model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, optional `thinking`, `tool_calls`), and `GENERIC` (tool results, shell exit codes, `invoke_subagent` child IDs, permission errors).

## Known limits

- **App / IDE `$PLUGIN_DATA`:** installed-plugin `$PLUGIN_DATA` was verified for CLI (`~/.gemini/antigravity-cli/plugin_data/<name>`), not yet with an installed plugin inside `Antigravity.app` or `antigravity-ide`.
- **Marketplace distribution:** `agy plugin install subspace@subspace` against a remote GitHub marketplace manifest has not yet been tested end-to-end.
- **Unobserved `Stop.terminationReason` values:** only `NO_TOOL_CALL` was observed (`Esc` and permission denial emitted no `Stop`); `ERROR`, `MAX_INVOCATIONS`, `USER_CANCELED`, etc. remain unobserved.
- **Other capabilities:** background shell commands (`fullyIdle: false` without subagents), `/swarm`, mid-session model switching, and Linux/WSL/native Windows remain unobserved.

## Primary sources

- Captures curated in [`fixtures/antigravity/1.5.17/`](../../fixtures/antigravity/1.5.17/) (macOS arm64, `agy 1.5.16`/`1.5.17`, `Antigravity.app 2.35.1`).
- Local CLI `agy`: `agy --version`, `agy --help`, `agy plugin --help`, `agy plugin validate --strict --json`, `agy plugin install`/`list --json`/`uninstall`.
- Official Antigravity documentation:
  - [Hooks](https://antigravity.google/docs/hooks.md)
  - [Plugins](https://antigravity.google/docs/plugins.md)
  - [CLI Reference](https://antigravity.google/docs/cli/reference.md)
  - [Documentation index (`llms.txt`)](https://antigravity.google/llms.txt)
