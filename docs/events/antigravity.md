# Antigravity hook events: what subspace subscribes to

Based on Antigravity CLI `agy 1.5.15` (`agy --version`, `agy --help`, `agy plugin --help`, `agy plugin validate --help`), local `agy plugin validate --strict` probes, and the official Antigravity customization, hooks and plugins documentation. Applies across the Antigravity surfaces: CLI (`agy`), desktop App (Antigravity 2.0) and IDE (`antigravity-ide`).

**Evidence status: pre-capture inventory.** No real captures or curated fixtures exist yet. Every classification below is provisional until backed by real captures curated in `fixtures/antigravity/<version>/`. Where documentation and captures differ, captures win.

## Classification

Antigravity defines **six** lifecycle events (`SessionStart`, `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`).

**Basis:** a local `command` handler that exits 0 with empty stdout and stderr.

**Synchronous runtime:** Antigravity currently supports only `type: "command"` handlers (no HTTP or prompt hooks) and runs hooks **synchronously**, blocking the agent loop with no `async` execution mode (`docs/hooks.md`, "Current Limitations"). `core/spool.sh` is already designed to stay fast enough to run synchronously (contract §1: "Sync must stay possible"), but contract §§1 and 7 will need an Antigravity note once captures confirm the runtime behavior and latency.

### Provisional subscribe candidates

| Event | Structure & matcher | When it fires (documented) | Observe-only reasoning & open checks |
|---|---|---|---|
| `SessionStart` | Flat handler array; no matcher | Once when a new conversation session starts | Optional `injectSteps` output. Must verify that silent exit 0 (or `{}` if required) injects nothing and produces no warning; also verify `--continue`/`--conversation` (resume) and `-p` mode. |
| `PostToolUse` | Grouped `{matcher, hooks}`; regex on tool name (`*` or `""` for all) | After a tool step completes (`toolCall`, `stepIdx`, optional `error`) | Docs say stdout "Expects an empty JSON object `{}`". Must verify whether empty stdout + exit 0 is silently accepted or triggers a parse warning/error. |
| `PreInvocation` | Flat handler array; no matcher | Before the model is called (`invocationNum`, `initialNumSteps`) | Optional `injectSteps` and `terminationBehavior` (`""` or omitted proceeds to the model call). Must verify silent exit 0 leaves the invocation untouched. |
| `PostInvocation` | Flat handler array; no matcher | After tool calls finish (`invocationNum`, `initialNumSteps`) | Optional `injectSteps` and `terminationBehavior` (`""` or omitted keeps default behavior; `"force_continue"` / `"terminate"` steer). Must verify silent exit 0 does not force continuation or termination. |
| `Stop` | Flat handler array; no matcher | When the execution loop terminates (`executionNum`, `terminationReason`, `error`, `fullyIdle`, `continuationActive`) | Docs mark `decision` as required (`"continue"` blocks stop; "Any other value allows the agent to stop"). Must verify whether empty stdout (or `{}`) allows normal stop with zero errors or UI notices. |

### Conditional — gated on "Never steer" capture verification

| Event | Structure & matcher | Why it cannot be subscribed without capture proof |
|---|---|---|
| `PreToolUse` | Grouped `{matcher, hooks}`; regex on tool name (`*` or `""` for all) | **Major "Never steer" risk.** The hooks reference marks `decision` (`"allow"`, `"deny"`, `"ask"`, `"force_ask"`) as **required** and defines no abstain / `"no_decision"` value. Returning `"allow"` would bypass permission prompts; `"ask"` or `"force_ask"` would force prompts on auto-allowed tools; `"deny"` would block execution. Captures must prove that silent exit 0 (or `{}` if required) falls through untouched across every execution policy (`always-proceed`, `proceed-in-sandbox`, `request-review`, `strict`, `--sandbox`) without approving, prompting, blocking or logging errors. If registering `PreToolUse` alters *any* permission outcome, move it to **Never subscribe**. |

### Not defined in Antigravity

Antigravity's six-event registry has no `SessionEnd`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUseFailure`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `Notification`, `Interrupt`, `PostModelSwitch`, `WorktreeCreate` or `WorktreeRemove`. Do not invent equivalents.

## Findings (pre-capture)

### 1. Configuration, scopes, matching and working directory

Hooks are declared in a `hooks.json` object whose top-level keys are **named hook groups**, each mapping to event arrays and an optional `"enabled": false` toggle. Multiple named hooks across configs and plugins are merged and executed sequentially.

- **Discovery locations:** workspace `.agents/hooks.json` (also `.agent/`, `_agents/`, `_agent/`, discovered by walking from the working directory up to the repository root), global `~/.gemini/config/hooks.json`, and bundled plugin `<plugin_dir>/hooks.json`.
- **Event structure differs by event:** `PreToolUse` and `PostToolUse` require grouped entries `[{"matcher": "*", "hooks": [...]}]`, where `matcher` is a regex matched against the lowercased step type with `CORTEX_STEP_TYPE_` stripped (e.g. `run_command`, `edit_file`, `browser_.*`; `*` or `""` matches all tools). `SessionStart`, `PreInvocation`, `PostInvocation` and `Stop` take a flat array of handler objects directly and ignore matchers.
- **Handler fields:** `type` (optional, default `"command"`), `command` (required; executed via `sh -c` on Unix and `cmd /c` on Windows; `~` is expanded), and `timeout` (optional integer seconds, default `30`).
- **Working directory:** the Antigravity hooks guide states that a hook command runs with its working directory set to **the directory containing `hooks.json`** (e.g. `.agents/` for a workspace config or `<plugin_dir>` for a plugin), while `payload.cwd` carries the agent's working directory. Some secondary summaries instead describe the workspace root for workspace hooks; the capture logger records `pwd` in `.meta` to settle this empirically.

### 2. Input/output contract, camelCase payloads and `envelope.v1.json`

Hook commands receive one JSON object on **stdin**. All documented keys use **camelCase** (protojson encoding):

- **Common fields:** `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName`, `lastUserInput`, `hookEventName`, `cwd`.
- **`PreToolUse` / `PostToolUse`:** `toolCall` (`id`, `name`, `args`), `stepIdx`, plus `error` on `PostToolUse` when the tool failed.
- **`PreInvocation` / `PostInvocation`:** `invocationNum`, `initialNumSteps`.
- **`Stop`:** `executionNum`, `terminationReason` (`NO_TOOL_CALL`, `MAX_INVOCATIONS`, `MAX_FORCED_INVOCATIONS`, `MAX_TOKEN_BUDGET_EXCEEDED`, `ERROR`, `USER_CANCELED`, `TERMINAL_STEP_TYPE`, `TERMINAL_CUSTOM_HOOK`, `INJECTED_RESPONSE`), `error`, `fullyIdle`, `continuationActive`.

**`envelope.v1.json` compatibility:** [`schema/envelope.v1.json`](../../schema/envelope.v1.json) currently requires `payload.hook_event_name` (snake_case). Because subspace preserves hook payloads byte for byte (contract §§1, 4), Antigravity payloads will carry `hookEventName` rather than `hook_event_name`. Before implementing the adapter, we must decide (with consumer apps in view) how `schema/envelope.v1.json` and contract §4/§9 accommodate camelCase payloads (for example relaxing/extending `envelope.v1.json` vs. bumping `v`).

**Empty stdout vs. `{}`:** the hooks documentation states that handlers must output a JSON object on stdout (`PostToolUse` expects `{}`; `PreToolUse` and `Stop` document a required `decision` field). By contrast, `core/spool.sh` writes nothing to stdout or stderr — and for Claude Code and Codex, printing anything to stdout injects model context on several events. Captures must test empty stdout first across all six events, and only test `{}` as a comparison if empty stdout triggers errors or alters behavior. If Antigravity requires `{}` on stdout, any change must stay isolated from Claude Code and Codex.

### 3. Plugin packaging, `PLUGIN_DATA` and distribution

Antigravity discovers native plugins from directories containing `plugin.json`, `.antigravity-plugin/plugin.json` or `.gemini-plugin/plugin.json` (plus explicit `plugins.json` registration).

- **Manifest:** `.antigravity-plugin/plugin.json` (`https://antigravity.google/schemas/v1/plugin.json`) supports `name`, `displayName`, `version`, `description`, `author`, `homepage`, `repository` and `disabled`. Using `.antigravity-plugin/plugin.json` also matches `core/spool.sh`'s existing `../.*-plugin/plugin.json` version lookup and release-please's `extra-files` pattern.
- **Root `hooks.json` is required:** native plugins do **not** run extension staging (`hooks/hooks.json` is staged only when importing a Gemini CLI or Claude Code extension). Verified locally with `agy plugin validate --strict --json` on `agy 1.5.15`:
  - `.antigravity-plugin/plugin.json` + root `hooks.json` passes `--strict` with exit 0 (`manifest: ".antigravity-plugin/plugin.json"`, `components.hooks: 1`).
  - `.antigravity-plugin/plugin.json` + `hooks/hooks.json` loads 0 hooks and fails `--strict` with warning: `"never loaded: plugin hooks are read only from hooks.json at the plugin root"`.
  - Adding `"async": true` to a handler in `hooks.json` produced no validator error or warning in `agy 1.5.15`, though hooks are documented as synchronous only.
- **Plugin environment (`PLUGIN_ROOT` and `PLUGIN_DATA`):** plugin command hooks receive `PLUGIN_ROOT` (the plugin directory) and, for installed plugins, `PLUGIN_DATA` (the plugin's persistent writable data directory) as environment variables. They are not substituted into `command`; hooks run with cwd set to the plugin root and read `$PLUGIN_DATA` from the shell environment. **Core impact:** `core/spool.sh` currently resolves `$ROOT` as `${SUBSPACE_DIR:-${CLAUDE_PLUGIN_DATA:-}}` and does not fall back to `PLUGIN_DATA`. Unless captures show `CLAUDE_PLUGIN_DATA` is also exported, `core/spool.sh` will need a `PLUGIN_DATA` fallback.
- **CLI management & validation:** `agy plugin list [--json]`, `install <target>` (supports `plugin[@marketplace]`, local directory, zip or URL), `uninstall <name>`, `enable <name>`, `disable <name>`, `validate [target] [--strict] [--json]`, `link <mp> <target>`. Enable/disable state is stored in `config.json` under `plugins.<dir-name>.enabled` and survives updates/reinstalls.
- **Planned distribution (Phase 3):** a dedicated dist repo `we-are-the-borg/subspace-antigravity` holding the plugin at its root (`.antigravity-plugin/plugin.json`, root `hooks.json`, `scripts/spool.sh`, `schema/`, `model/`) plus its marketplace manifest, validated in CI with `agy plugin validate --strict`. Exact marketplace file path, schema and uninstall cleanup behavior are open capture items below.

### 4. Surfaces, processes, subagents and transcripts

Antigravity ships three surfaces with product-specific data directories documented for `transcriptPath` and `artifactDirectoryPath`:

- **CLI (`agy`):** `antigravity-cli/` (`~/.gemini/antigravity-cli/settings.json`)
- **Desktop App (Antigravity 2.0):** `antigravity/`
- **IDE (`antigravity-ide`):** `antigravity-ide/`

Process ownership (`$PPID`), terminal environment inheritance, subagent visibility (`invoke_subagent` / `/swarm`) and transcript file schemas are not sufficiently specified by documentation for consumer contract rules and must come from captures.

## Open capture questions

These questions must be answered by real captures in `tools/hook-capture/antigravity/` before curating fixtures or changing `core/`, `schema/` or `docs/contract.md`:

1. **"Never steer" on `PreToolUse` and stdout contract (empty stdout vs. `{}`):**
   - Does silent exit 0 (empty stdout, empty stderr) work cleanly across all six events with no hook errors, warnings or UI noise, or does Antigravity require `{}` on stdout (and on which events)?
   - On `PreToolUse`, across execution policies (`always-proceed`, `proceed-in-sandbox`, `request-review`, `strict`, `--sandbox`) and across auto-allowed, prompt-requiring and denied tool calls, does registering the hook leave every permission decision identical to having no hook?
   - What happens on non-zero exit or timeout, and does `async: true` have any runtime effect?
2. **Raw payloads, camelCase keys and `envelope.v1.json` compatibility:**
   - Exact keys and types on every one of the six events across CLI, App and IDE (confirming `hookEventName`, `conversationId`, `toolCall`, `stepIdx`, `error`, `modelName`, `lastUserInput`, `cwd`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `terminationReason`, `fullyIdle`, `continuationActive`).
   - Does `PostToolUse` include tool output/response or only `toolCall` and `error`? Does a user-denied tool fire `PostToolUse` or nothing? Does `PreToolUse` fire before or after a permission dialog?
   - How does `modelName` behave (`"auto"` vs. concrete model ID, mid-session switches), and is reasoning effort (`--effort`) present in payloads or only in transcripts?
   - What is the hook process's actual `pwd` relative to `.agents/hooks.json` and `payload.cwd`?
3. **Event firing semantics across modes and surfaces:**
   - Does `SessionStart` fire only on brand-new sessions, or also on `--continue` / `--conversation <id>` (resume) and `-p` (non-interactive print mode)?
   - Exact firing cadence of `PreInvocation` and `PostInvocation` within multi-tool turns, and relative to `PreToolUse`/`PostToolUse`/`Stop`.
   - Observed `Stop.terminationReason` values on normal completion, user interrupt (`Esc`/`Ctrl-C`), error and `-p` exit; whether `Stop` always lands before process exit.
   - Any payload or lifecycle differences between CLI (`agy`), desktop App (Antigravity 2.0) and IDE (`antigravity-ide`).
4. **Plugin packaging, `PLUGIN_DATA` path, marketplace, detection and uninstall:**
   - Exact filesystem paths of `$PLUGIN_ROOT` and `$PLUGIN_DATA` for an installed plugin across CLI, App and IDE (shared vs. per-surface, any config-dir env override).
   - Which `AGY_*`, `ANTIGRAVITY_*`, `GEMINI_*`, `GOOGLE_*`, `PLUGIN_*` and `CLAUDE_*` environment variables are exported to hooks (especially whether `CLAUDE_PLUGIN_DATA` is absent).
   - Whether `agy plugin uninstall` deletes `$PLUGIN_DATA` (like Claude Code) or preserves it (like Codex).
   - Exact `agy plugin list --json` schema and `config.json` path for consumer detection (contract §11), plus marketplace file layout and `agy plugin install subspace@subspace` / upgrade behavior.
5. **Process model (`pid`) and terminal identifiers (`terminal`):**
   - What is `$PPID` and the full parent process chain through PID 1 in interactive CLI, headless `-p`, desktop App and IDE?
   - Is `$PPID` a per-session process or a shared host/daemon/Electron process across sessions (determining whether apps may use `pid` for session liveness or must use a timeout)?
   - Which of contract §4's twelve allowlisted terminal environment variables are inherited by hooks in CLI, App and IDE, and whether they identify the active terminal tab or a shared parent process.
6. **Subagents and background tasks:**
   - Do hooks fire inside subagents spawned via `invoke_subagent` (or `/swarm`)? If so, what `conversationId` and `transcriptPath` do they carry, and is there any parent-child link field in the payload or transcript?
   - What do `PreToolUse`/`PostToolUse` payloads look like for `invoke_subagent` and background `run_command`?
   - How does `Stop.fullyIdle` behave when background commands or subagents are still running?
7. **Transcripts and artifacts:**
   - Exact format of `transcriptPath` (JSONL record types, timestamps, token usage, model, effort, tool results/exit codes, subagent references) across CLI, App and IDE.
   - Whether `transcriptPath` is materialized and flushed at hook time, or lags, or can be empty/null (e.g. in `-p` mode).
   - What `artifactDirectoryPath` contains and whether anything in it is relevant to consumers.
8. **Platforms, shells, synchronous latency and paths with spaces:**
   - Verified platforms (macOS first; Linux, WSL, native Windows status); outer `sh -c` behavior and silence.
   - Behavior when the workspace path or plugin/script path contains spaces.
   - Observed wall-clock latency of synchronous hook invocations during multi-tool turns.

## Primary sources

- Local CLI `agy 1.5.15`: `agy --version`, `agy --help`, `agy plugin --help`, `agy plugin validate --help`, and `agy plugin validate --strict --json`.
- Official Antigravity documentation:
  - [Hooks](https://antigravity.google/docs/hooks.md)
  - [Plugins](https://antigravity.google/docs/plugins.md)
  - [CLI Reference](https://antigravity.google/docs/cli/reference.md)
  - [Documentation index (`llms.txt`)](https://antigravity.google/llms.txt)
