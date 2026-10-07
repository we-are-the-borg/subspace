# Codex hook events: what subspace subscribes to

Based on `codex-cli 0.159.3`, official source tag [`rust-v0.159.3`](https://github.com/openai/codex/tree/rust-v0.159.3), and its CLI help (`codex --help`, `codex features list`, the plugin subcommands).

**Evidence:** the pinned source, plus user-started macOS captures curated in [`fixtures/codex/0.159.3/`](../../fixtures/codex/0.159.3/). Where they differ, the captures win. Installed-plugin checks are in [`tools/e2e/codex.md`](../../tools/e2e/codex.md).

## Classification

The version defines twelve lifecycle events. Hook support is stable and enabled by default through `features.hooks`; the local `codex features list` also reports `hooks stable true`. [Event registry][events]; [feature default][feature].

**Basis:** a trusted local plugin `command` handler, `async: true`, empty stdout and stderr, exit 0. Async dispatch schedules work without awaiting its completion; control effects are enabled only for synchronous handlers. This does **not** mean zero overhead: discovery, serialization, scheduling, hook status events and background file I/O still occur. “Observe-only” here means no hook verdict, rewritten input, model context, forced foreground command wait, or retry/continuation. [Dispatcher][dispatch]; [control-effects gate][control]; [background runtime][runner]; [core integration][core].

Silence is essential even with async: context entries from a background hook can be injected into the active turn or next prompt. An async flag alone is not a guarantee against steering. [Async result handling][async-results].

### Subscribe

The adapter subscribes to this list using the handler behavior above. Match all occurrences by omitting the matcher; `*` also matches all. Source links in the final column include the event serializer and empty-output parser. [Matching rules][match].

| Event | Matcher input, if filtering | Observe-only reasoning |
|---|---|---|
| `SessionStart` | Start source (`startup`, `resume`, `compact`, `fork`) | Async does not await completion. Silent exit 0 supplies no context and no stop request. Plain stdout would become context, so it must stay empty. [Start handler][start]. |
| `UserPromptSubmit` | Ignored | Silent exit 0 neither blocks nor appends context. Background dispatch supplies no synchronous outcome. [Prompt handler][prompt]. |
| `PreToolUse` | Canonical tool name and compatibility aliases | Empty output leaves input untouched and supplies no denial or context. Async cannot apply control effects. [Tool-start handler][pre]. |
| `PermissionRequest` | Tool name and aliases | A silent background handler supplies no verdict; the existing guardian/user review proceeds. Registering it does not itself create an approval request. [Permission handler][permission]; [approval routing][approvals]. |
| `PostToolUse` | Tool name and aliases | Runs after tool output is returned, including the captured nonzero shell exit. Silent exit 0 adds no feedback/context and requests no blocking/retry. Async outcomes do not alter the synchronous result. [Tool-result handler][post]; [core integration][core]. |
| `PreCompact` | Compaction trigger (`manual`, `auto`) | Empty output supplies no stop request; async cannot stop compaction. [Compaction handlers][compact]. |
| `PostCompact` | Compaction trigger (`manual`, `auto`) | Same empty-output/control gate; adds no context and does not restart compaction. [Compaction handlers][compact]. |
| `SubagentStart` | Agent type/role | Uses the start parser: silence contributes no context. Thread-spawned child startup/fork triggers it; internal/system subagents skip start hooks. [Start handler][start]; [start dispatch][core-start]. |
| `SubagentStop` | Agent type/role | Empty output produces no continuation. Async cannot apply a block/continuation verdict. This is a child **turn** completion, not proof that its thread has been destroyed. [Stop handlers][stop]; [stop dispatch][core-stop]. |
| `Stop` | Ignored | Empty output produces no continuation or stop verdict. Background dispatch does not await the script or use its control outcome. [Stop handlers][stop]. |
| `Interrupt` | Ignored | The active turn is already detached; root-only hook has no control outcome. Supports async, with a short timeout. Silent exit 0 contributes no warning. [Interrupt handler][interrupt]; [interrupt dispatch][core-end]. |

### Never subscribe under this adapter policy

| Event | Reason |
|---|---|
| `SessionEnd` | Codex forcibly converts `async: true` to synchronous execution and emits a configuration warning. It awaits command completion during root-thread teardown, with a default 1-second timeout, clamped to 1–3 seconds. Silence prevents a decision, but cannot remove that foreground wait. Exclude it; do not detach a helper or disguise it as async. [Discovery normalization][normalize]; [SessionEnd handler][end]; [teardown integration][core-end]. |

This is a limitation of the event, not a finding that all Codex hooks are unusable. The other eleven support background dispatch. If requiring `SessionEnd` becomes mandatory, stop and revisit the requirement rather than work around its synchronous runtime. [Normalization][normalize]; [dispatcher][dispatch].

### Skip

- Legacy `notify` (`agent-turn-complete`): separate configuration, JSON appended as one argv argument rather than stdin, fire-and-forget with output discarded. It lacks the lifecycle `hook_event_name` format and duplicates turn completion. Prefer lifecycle hooks; do not overwrite a user's existing notifier. [Legacy notifier][notify]; [registry integration][registry].
- Handler types `mcp_tool`, `prompt`, `agent`: only `command` meets this adapter's dependency rules. MCP handlers are synchronous; prompt/agent handlers are parsed but skipped. These are handler types, not additional events. [Handler configuration][config]; [handler discovery][normalize]; [control gate][control].
- Claude-specific names such as `PostToolUseFailure`, `Notification`, `WorktreeCreate`, `WorktreeRemove` and `StopFailure` are not Codex lifecycle events in this tag. Do not invent equivalents. [Complete event registry][events].

## Findings

### 1. Events, configuration, scopes and matching

Lifecycle configuration is either a `hooks.json` object containing `hooks`, event names, matcher groups and handler arrays, or inline TOML `[[hooks.<Event>]]` and `[[hooks.<Event>.hooks]]` tables. Discovery combines matching hooks from active config layers and enabled plugins, rather than replacing lower-layer hooks. If JSON and TOML both contain hooks in one layer, it combines them and warns. User and project locations are normally `$CODEX_HOME/hooks.json` / `config.toml` and `<repo>/.codex/hooks.json` / `config.toml`; managed/system layers also exist. Project hooks require an active trusted project layer. [Configuration types][config]; [discovery][discovery]; [official hooks guide](https://learn.chatgpt.com/docs/hooks#where-codex-looks-for-hooks).

Matchers omitted, empty or `*` mean all. ASCII alphanumeric/underscore/pipe-only patterns are exact alternatives; other patterns use Rust regex matching. Tool aliases can also match, but a handler is selected only once per tool invocation. `UserPromptSubmit`, `Stop`, `Interrupt` ignore matchers. [Matcher implementation][match]; [selection/deduplication][dispatch]. The subscribe table identifies the other events' matching inputs, as the source describes them.

Non-managed hooks, including plugin hooks, require trust in the exact current definition hash; changed definitions are skipped pending review. `/hooks` provides the review UI. Managed policy may prohibit non-managed hooks altogether. Hook trust is an installation concern, distinct from permission approval for the agent's tools. [Trust discovery][discovery]; [official trust guide](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks). Do not recommend bypassing hook trust as ordinary installation.

### 2. Input, environment and timeout

Codex serializes one JSON value and writes its bytes to the command's stdin. It closes stdin after writing, drains stdout/stderr concurrently, and includes stdin writing in the timeout. The hook runs with the requested local working directory. Lifecycle input is not passed as a JSON argv argument. [Command runner][runner]; [event serializers][schema]; [local cwd choice][core].

Plugin hooks receive `PLUGIN_ROOT` and `PLUGIN_DATA`, plus the compatibility aliases `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA`. Codex also replays the session environment snapshot, filtering restricted names. The inspected launcher/discovery sets **no dedicated hook session-ID, cwd, or agent-PID environment variable**: use stdin for the documented session/cwd information. Do not assume an inherited `CODEX_THREAD_ID`, `CLAUDE_PID`, `CODEX_HOME` or `$PPID` is an adapter contract. [Plugin environment][plugin-env]; [environment replay][runner].

Timeout defaults to 600 seconds for most events, minimum 1 second. `Interrupt` and `SessionEnd` default to 1 second and clamp to 1–3 seconds. Timeout/spawn failure is a Codex hook error even if the intended script would normally exit 0. No timeout can promise delivery during teardown. [Timeout normalization][timeouts]; [runner][runner].

**PID:** `pid` stays the script's `$PPID`. User-started captures show the session's `codex` process in headless/`--no-daemon` runs and the same shared `app-server` in multiple daemon sessions. Apps must use a timeout since the last event for Codex session liveness, never treat this PID as a session-specific process. No PID lookup or envelope bump is needed. See [contract §6](../contract.md#codex-cli-01593) and the [fixture findings](../../fixtures/codex/0.159.3/README.md).

### 3. Sync, async, output and exit status

Command hooks are synchronous by default. With `async: true`, the dispatcher queues background tasks (at most eight running per session) and omits them from the synchronous outcome. Completion status is delivered later. Shutdown aborts outstanding tasks and waits for cancellation; there is no durable queue or guaranteed drain. `SessionEnd` is the explicit exception above. [Dispatcher][dispatch]; [runtime/semaphore/shutdown][runner]; [normalization][normalize].

| Output/status | Runtime behavior relevant to subspace |
|---|---|
| Exit 0, empty stdout/stderr | The inspected event parsers produce empty entries and no context/control effect. This is the required handler behavior. [Start][start], [prompt][prompt], [pre-tool][pre], [permission][permission], [post-tool][post], [compact][compact], [stop][stop], [interrupt][interrupt], [end][end]. |
| Plain stdout | Can become model context for `SessionStart`, `SubagentStart`, `UserPromptSubmit`, including asynchronously. Some other parsers ignore it or report invalid output. Never rely on those differences; emit nothing. [Start][start]; [prompt][prompt]; [async integration][async-results]. |
| JSON stdout | Depending on event, can supply additional context, warnings, permission/input changes, blocking or continuation. Async disables control effects but retains context/warnings; it is not an output sink. [Output schemas][schema]; [control gate][control]; [background result filtering][runner]. |
| Exit 2 / other nonzero / timeout | Exit 2 can block or request continuation for applicable synchronous events using stderr. Async cannot apply these control effects, but failures still produce hook diagnostics. Always return 0 and suppress errors in the adapter; launcher failures remain possible. [Pre-tool parser][pre]; [permission parser][permission]; [stop parser][stop]; [runner][runner]. |

Local hooks produce start/completion status events even when silent. That diagnostic activity and normal background resource use are unavoidable registration costs; they do not themselves supply context or change approval results. Do not advertise absolute zero latency or invisibility in Codex's hook UI. [Core event emission][core]; [async results][async-results].

### 4. Registering a silent hook

The tables above classify all twelve events. For the eleven background candidates, the source traces selection → scheduling → event parser → empty context/control outcomes. Permission routing explicitly falls through to the existing reviewer when the hook returns no decision; stop handlers have no continuation with empty output. This source reasoning establishes eligibility; the captures establish the observed coverage (see [Known limits](#known-limits)). [Dispatch][dispatch]; [approvals][approvals]; [stop][stop].

### 5. Distribution and uninstall

Codex has plugins, versioned local caches and Git/local/npm marketplaces. Marketplace discovery prefers `.agents/plugins/marketplace.json`, then `.agents/plugins/api_marketplace.json`, with Claude/Cursor compatibility fallbacks. Plugin entries can be local (`./`, relative to the marketplace root) or Git (`git-subdir`, `path`, `ref`, `sha`). [Marketplace implementation][marketplace].

**Version-specific packaging restriction:** although current official docs describe portable root `plugin.json` hooks, this tag's local loader returns no hook sources for `AgentPlugin` format. It loads hooks for compatibility manifests instead. The adapter uses `.codex-plugin/plugin.json` with `hooks/hooks.json` for the 0.159.3 local adapter; do not also add a preferred Agent Plugins root manifest that suppresses those hooks. Recheck this restriction before migrating formats or claiming other execution surfaces work. [Pinned loader][plugin-loader]; [manifest selection][manifest-select]; [current packaging guide](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks).

Installation (commands in the [README](../../README.md#codex)):

1. The dist repo `we-are-the-borg/subspace-codex` holds the plugin at its root and `.agents/plugins/marketplace.json` with plugin source `"./"`. Its `main` only moves on releases, so the marketplace snapshot is always a released state. Claude's marketplace is a separate repository. [Local source support][marketplace].
2. User adds the marketplace, then installs `codex plugin add subspace@subspace`. CLI help confirms these command forms; the names assume both plugin and marketplace remain `subspace`. This writes the marketplace/plugin registration in Codex configuration as the documented installation exception. No project config file or overwrite of existing user hook arrays is needed. [CLI commands][plugin-cli]; [user-config mutations][plugin-manager].
3. User reviews/trusts the installed handlers in `/hooks`; installed/enabled is insufficient without trust. [Trust discovery][discovery].

For reproducibility, `ref` can be a tag or full commit SHA, and a plugin entry also supports `sha`. Tags can be moved; a full SHA is an immutable revision. The marketplace itself can optionally be pinned with `codex plugin marketplace add <repo> --ref <commit-or-tag>`; a frozen marketplace must be deliberately updated for later releases. Normal installs follow the dist repo's `main`; pin a release tag or SHA only for isolated verification. [Source selectors][marketplace]; [marketplace source parser][marketplace-source]; [revision resolution][marketplace-git]; local `codex plugin marketplace add --help`.

The cache layout is `$CODEX_HOME/plugins/cache/<marketplace>/<plugin>/<version>`; legacy manifests without a version use `local`. Installation prunes other valid version directories. Adapter versions are owned by release-please, never bumped by hand. [Store/version selection][store].

**Uninstall does not purge plugin data.** `codex plugin remove subspace@subspace` removes its cache and user plugin config entry, but the pinned uninstall path never removes `plugins/data`. No uninstall lifecycle handler is provided by the twelve-event registry. Clean removal therefore requires: stop sessions still using the adapter, remove the plugin, then explicitly delete only its resolved `$ROOT` (including any override) if the user wants to purge events. Optionally remove the marketplace with `codex plugin marketplace remove subspace` when no other plugin needs it; that removes marketplace registration/snapshot, not adapter data. Do not claim Claude's automatic uninstall cleanup for Codex. [Store uninstall][store]; [manager uninstall][plugin-manager]; [marketplace removal][marketplace-remove]; [event registry][events]; local `codex plugin remove --help`.

### 6. Root and installed/active detection

One root per agent: the hook uses Codex's supplied `CLAUDE_PLUGIN_DATA` compatibility alias of `PLUGIN_DATA`, with optional `SUBSPACE_DIR` for tests/development. This lets the shared writer stay unchanged. For compatibility plugin `subspace` in marketplace `subspace`, the pinned store formula yields:

| Case | Codex `$ROOT` (macOS installed-plugin paths verified) |
|---|---|
| Default Codex home | `~/.codex/plugins/data/subspace-subspace/` |
| Custom `CODEX_HOME` | `$CODEX_HOME/plugins/data/subspace-subspace/` |
| `SUBSPACE_DIR` override | Exactly `$SUBSPACE_DIR` |

The formula is `<plugin>-<marketplace>` in the versioned implementation, not a promised permanent public path. Plugin code must use the supplied data variable; installed-plugin runs verified the default/custom-home paths on macOS, so consumers can resolve these frozen names/paths. Portable Agent Plugins use a different hash-derived data root for MCP, so changing manifest format needs a fresh location decision. [Store roots][store]; [hook environment][plugin-env]; [Codex home resolution][codex-home].

The adapter keeps the existing root layout (`events/<UTC day>/`, `schema/`, `plugin.json`) and writes `source: codex`. On `SessionStart` it refreshes the adapter version and schema; apps watch per-source roots. Envelope `v` stays 1; `pid` is described per source in [contract §§2–6](../contract.md). Schema v1 now also accepts a null `transcript_path`, observed in ephemeral sessions, without changing envelope fields.

Codex's plugin config has `enabled` and MCP policies, not Claude's `userConfig.retention_days` prompt or injected retention variable. Decision: keep the default three-day cleanup in the unchanged shared writer. The Codex adapter declares no `userConfig` and adds no retention override file or undocumented configuration key. The root survives uninstall, so retention runs only while hooks execute; there is no cleanup service when Codex stops. [Plugin config type][plugin-config]; [uninstall implementation][store]; [existing retention policy](../contract.md#5-retention).

Installed/enabled detection: `codex plugin list --json` returns `installed` and `available` arrays; installed entries include `pluginId`, `marketplaceName`, `version`, `installed`, `enabled`. Match the exact adapter ID `subspace@subspace`, both state booleans and the relevant marketplace. Apps with an app-server connection can use `plugin/installed` instead. Effective configuration can still disable hooks or require managed hooks; fresh/changed handler trust also matters. [CLI JSON model][plugin-cli]; [installed protocol][plugin-protocol]; [hook discovery][discovery].

Active detection is separate: require recent event arrival and the root's `plugin.json` refreshed at `SessionStart`. That marker is historical evidence, not proof of current enablement or liveness; because uninstall preserves data, even an uninstalled adapter can leave it behind. Session liveness uses a timeout, as decided from the process captures above. [Uninstall][store]; [existing detection distinction](../contract.md#11-detecting-subspace).

### 7. Correlation and transcripts

The user-started captures establish these fields and semantics. Evidence is in [the fixture scenarios](../../fixtures/codex/0.159.3/README.md); the consumer rules are in [contract §6](../contract.md#codex-cli-01593).

| Field/event | Observed meaning and consumer constraint |
|---|---|
| `session_id` | The root session, also on child events. A child's separate UUID is in `agent_id`. |
| `turn_id` | Distinguishes root/child turns; qualify by root session and optional `agent_id`. `SessionStart` has no turn ID. Resume keeps root session ID and transcript path. |
| `tool_use_id` | Pairs pre/post tool calls; `PermissionRequest` has none. Requests add `description` to their tool input, so compare stable command fields instead of whole objects or file order. |
| `agent_id`, `agent_type` | Child UUID and role on child lifecycle/tool events. Captured spawn responses return task paths (`/root/alpha`), encoded as JSON strings, rather than the child UUID. |
| `SubagentStop` | Per child turn: alpha was reused and stopped twice with different turn IDs. Its `transcript_path` is the root rollout; `agent_transcript_path` is the child rollout. Child starts/tools reference the child rollout. |

To link a spawn to a child, read the child's rollout `session_meta`: `id`, root `session_id`, `parent_thread_id`, and `source.subagent.thread_spawn.agent_path` bridge the returned task path and child UUID. Parallel child turns overlapped; their async start/stop files arrived in a misleading order. Leave an unlinked child unassigned until metadata exists. Nested spawning and child reuse across resume remain unobserved.

Shell `PostToolUse.tool_response` can contain stdout or be empty. The observed failed command (`exit 7`) produced an empty response with no exit-code field; its exit code is in the rollout/CLI stream. Manual and automatic review each emitted `PermissionRequest`; a remembered approved command emitted no new permission event. The user's confirmed “Reject and tell Codex what to do instead” action produced `Interrupt`, with no post or `Stop` for the rejected turn. This does not establish other rejection gestures.

A running sleep's post arrived after interruption and after the next turn's `Stop`. A separate immediate-exit run had no post. `Interrupt` does not guarantee process termination or delivery of all terminal events. Final `Stop` payloads in headless and ephemeral runs arrived with incomplete logger `.meta` work, consistent with async teardown cancellation; exact cancellation cause is not proven by those files.
Local rollouts use `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<local timestamp>-<thread-id>.jsonl`, sometimes with a separate rollout-ID suffix; archived rollouts use `archived_sessions`. These dates are local, unlike subspace's UTC day folders. Hooks obtain `transcript_path` from the live thread and ensure materialization; absence/errors can yield null. Apps should prefer captured paths and tolerate missing/lagging/changed internal formats, including paginated or compressed storage. subspace must not read, materialize or rewrite transcripts itself. [Rollout paths][rollout]; [filename variants][rollout-name]; [archive root][rollout-root]; [hook path acquisition][transcript]; [paginated/compression implementation][rollout].

Usage/model/history belong to Codex's rollout/protocol rather than a new interpreted subspace payload: protocol defines token-count events and session metadata. Collected rollouts contain token counts, session/parent metadata and shell exit codes. Ephemeral sessions instead sent `transcript_path: null` on every hook; their CLI stream still contained usage. [Protocol usage and metadata][metadata]; [existing transcript policy](../contract.md#8-transcripts).

### 8. Platforms and shells

On macOS/Linux the explicit turn-environment shell, when supplied, is invoked using its derived non-login command arguments. Otherwise the hook runner uses the session snapshot's `SHELL` or `/bin/sh`, with `-lc`. Windows uses the explicit shell if present, otherwise `COMSPEC` or `cmd.exe` with `/C`; `commandWindows` selects an alternate configured command on Windows. Codex does **not** universally run hooks in Git Bash. [Shell selection][shell-config]; [launcher/default shell][runner]; [Windows override][normalize].

Observed: macOS 27.0 arm64, including a cwd containing spaces. Linux, WSL and native Windows remain unverified; the adapter requires POSIX `sh` and standard utilities. Native Windows needs an explicitly available POSIX shell plus standard utilities, path/quoting validation and a Windows command override; native support without that remains blocked by the existing POSIX runtime constraint. Do not change the user's shell to make the adapter work. Whether outer-shell startup emits text before the silent script runs is a capture question. [Launcher][runner]; [existing platform constraint](../contract.md#10-platforms).

## Known limits

The captures in [`fixtures/codex/0.159.3/`](../../fixtures/codex/0.159.3/README.md) observed all eleven subscribed events across headless and interactive runs, tool failure, manual rejection, interrupt, compaction and resume. Still open:

- **Delivery:** teardown can cancel outstanding async hooks; delivery of terminal events is not guaranteed.
- **Tool visibility:** inner code-mode calls and MCP-specific tool calls are unobserved.
- **Permissions:** concurrent identical permission requests are untested; correlate stable command fields and IDs.
- **Subagents:** nested spawning was unavailable; child reuse across resume is untested.
- **Platforms:** only macOS is verified (including paths with spaces); Linux, WSL and native Windows are not.
- **Transcripts:** rollout formats and their availability at event time are not guaranteed.

## Primary sources

All source links below pin the installed version. The live [official hooks guide](https://learn.chatgpt.com/docs/hooks) and [plugin packaging guide](https://developers.openai.com/plugins/build/plugins) were also read; their current content is corroborative, not a substitute for this tag.

[events]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/lib.rs#L22-L55
[feature]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/features/src/lib.rs#L1220-L1225
[config]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/config/src/hook_config.rs
[discovery]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs
[plugin-env]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs#L238-L290
[normalize]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs#L504-L650
[timeouts]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs#L740-L764
[control]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/mod.rs#L140-L157
[dispatch]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/dispatcher.rs#L32-L188
[runner]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/command_runner.rs
[match]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/common.rs#L128-L194
[start]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/session_start.rs
[prompt]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/user_prompt_submit.rs
[pre]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/pre_tool_use.rs
[permission]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/permission_request.rs
[post]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/post_tool_use.rs
[compact]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/compact.rs
[stop]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/stop.rs
[interrupt]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/interrupt.rs
[end]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/events/session_end.rs
[notify]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/legacy_notify.rs#L29-L84
[registry]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/registry.rs#L118-L183
[schema]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/schema.rs
[core]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs
[core-start]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs#L128-L185
[core-stop]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs#L393-L475
[core-end]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs#L477-L552
[async-results]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs#L777-L819
[approvals]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/tools/approvals.rs#L478-L534
[shell-config]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/session/mod.rs#L5172-L5204
[subagent-identity]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/hook_runtime.rs#L1042-L1062
[transcript]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/session/mod.rs#L5066-L5085
[spawn]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/tools/handlers/multi_agents/spawn.rs#L195-L249
[metadata]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/protocol.rs
[rollout]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/rollout/src/recorder.rs
[rollout-name]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/rollout/src/rollout_file_name.rs#L8-L76
[rollout-root]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/rollout/src/lib.rs#L86-L87
[marketplace]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/marketplace.rs
[plugin-loader]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/loader.rs#L940-L963
[manifest-select]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/utils/plugins/src/plugin_namespace.rs
[store]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/store.rs
[plugin-manager]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/manager.rs#L2230-L2350
[marketplace-source]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/marketplace_add/source.rs#L18-L59
[marketplace-git]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/marketplace_upgrade/git.rs#L9-L47
[marketplace-remove]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/marketplace_remove.rs#L81-L106
[plugin-cli]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/cli/src/plugin_cmd.rs
[plugin-config]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/config/src/types.rs#L1002-L1011
[plugin-protocol]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/app-server-protocol/src/protocol/v2/plugin.rs#L698-L735
[codex-home]: https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/utils/home-dir/src/lib.rs
