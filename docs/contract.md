# Contract: subspace ↔ consumer apps

Version 1. Payload facts are backed by real captures in `fixtures/<source>/<version>/`. One `$ROOT` per source, with the same layout and envelope everywhere. Mapping documents (§12) let apps read target fields out of the raw payloads instead of depending on each agent's format. Claude Code's session status file is a read-only side source (§13).

subspace **only observes** coding agents. For each supported agent (a *source*, §4) an adapter in `adapters/<source>/` writes every hook event as a file into that source's shared folder `$ROOT` (§2). Local apps read those folders; all interpretation happens in the apps. Sources: Claude Code and Codex. Codex payload facts come from user-started macOS captures of CLI 0.159.3 in `fixtures/codex/0.159.3/`; installed-plugin checks are described in `tools/e2e/codex.md`.

Consumers today: **The Collective** and **Unimatrix Zero**, both native macOS apps (Swift). More can read the same folders without changes to subspace.

## 1. Principles

- **Observe, never steer.** All hooks are `command` hooks with `async: true`. The script always exits 0 and writes nothing to stdout or stderr. On some events the agent would feed stdout to the model as context, and a nonzero exit shows a hook error (see `docs/events/<source>.md`). An event whose registration alone changes the agent's behavior is never subscribed.
- **Sync must stay possible.** `async: true` is the default, but a later release may drop it if async misbehaves. Every invocation must therefore be fast enough to run synchronously.
- **No runtime dependencies.** The hook script is POSIX `sh` with standard utilities. No `node`, `jq` or `python`.
- **Payload unchanged.** The agent's hook JSON is wrapped in an envelope (§4), never rebuilt or truncated.
- **User scope only** (Claude Code: `/plugin install … --scope user`; Codex: `codex plugin add subspace@subspace`). Installation may register the marketplace/plugin in the agent configuration; the hook itself never writes there.
- **The plugin writes only inside `$ROOT`** (§2). Never into repos or the agent's configuration.

## 2. Location

**One `$ROOT` per source**: each adapter writes into its own plugin data directory, so uninstalling one agent's adapter never touches another's events. Layout (§3) and event files (§4) are the same in every root, and `source` in each envelope names the agent. Apps resolve the root of every source they support and watch each of them; a missing root means that adapter isn't installed or hasn't run yet.

### Claude Code (`claude-code`)

`$ROOT` is the plugin's data directory, which Claude Code passes to hooks as `CLAUDE_PLUGIN_DATA`:

```
~/.claude/plugins/data/subspace-subspace/
```

The name is `<plugin>-<marketplace>`; both are `subspace` and must never change, because apps rely on the path.

| Case | Path apps must use |
|---|---|
| Default | `~/.claude/plugins/data/subspace-subspace/` |
| `CLAUDE_CONFIG_DIR` set | `$CLAUDE_CONFIG_DIR/plugins/data/subspace-subspace/` |
| `SUBSPACE_DIR` set | `$SUBSPACE_DIR` (tests, and development with `claude --plugin-dir`, where Claude Code uses `subspace-inline` instead) |

The plugin itself uses `$SUBSPACE_DIR` if set, otherwise `$CLAUDE_PLUGIN_DATA`.

Claude Code deletes the directory when the plugin is uninstalled, including all events.

### Codex (`codex`)

The adapter uses `.codex-plugin/plugin.json` and the `.agents/plugins/marketplace.json` of its distribution repository `we-are-the-borg/subspace-codex`. The plugin and marketplace names are both frozen at `subspace`, independently of Claude Code's identically named marketplace in `we-are-the-borg/subspace-claude-code`. Codex 0.159.3 supplies `PLUGIN_DATA` and its equal compatibility alias `CLAUDE_PLUGIN_DATA`; the shared writer consumes the latter, avoiding an agent-specific branch in the core.

| Case | Path apps must use |
|---|---|
| Default | `~/.codex/plugins/data/subspace-subspace/` |
| `CODEX_HOME` set | `$CODEX_HOME/plugins/data/subspace-subspace/` |
| `SUBSPACE_DIR` set | `$SUBSPACE_DIR` (tests/development) |

These paths and data survival after uninstall are established by the pinned implementation ([store](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core-plugins/src/store.rs), [hook environment](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs#L238-L290)); installed-plugin delivery at both the default and custom home was verified on macOS (§11). Uninstall tests in both homes confirmed cache/registration removal and preservation of marker, schema and events. The writer uses `$SUBSPACE_DIR` if set, otherwise the supplied data directory; it never reconstructs a home path.

Codex **keeps the data directory after uninstall**. A stale root or `plugin.json` does not establish that the plugin is installed. Cleanup runs only while hooks run (§5); after uninstall events remain until explicitly removed by the user. Stop sessions using the plugin before uninstalling or purging data.

## 3. Layout

```
$ROOT/
├── plugin.json                      # refreshed on SessionStart (§11)
├── schema/                          # refreshed on SessionStart
│   ├── envelope.v1.json             # JSON Schema of event files (§4)
│   ├── mapping.v1.json              # JSON Schema of mapping documents (§12)
│   ├── result.v1.json               # JSON Schema of a mapping's result for this source (§12)
│   └── session-status.v1.json       # Claude Code only: JSON Schema of a session-status mapping's result (§13)
├── model/
│   ├── <source>.json                # mapping document of this source, refreshed on SessionStart (§12)
│   └── claude-code-session.json     # Claude Code only: mapping for its session status files (§13)
└── events/
    ├── 2026-09-29/                  # one folder per UTC day
    └── 2026-09-30/
        ├── .1790000000-4711-a8f3.tmp   # being written, ignore
        └── 1790000000-4711-a8f3.json   # one event
```

**Everything in `$ROOT` belongs to the plugin.** It writes every delivered subscribed event once its hooks are enabled and trusted, whether an app is running or not. Claude Code creates `$ROOT` itself (mode `0755`) when the first session starts after installation (Codex: the observed default data root was `0700`; its initial creation was not independently recorded, and the writer creates it if absent); the plugin creates `schema/`, `model/`, `events/` and the day folders. Until then `$ROOT` may not exist.

**Apps only read.** They never create, modify or delete anything in `$ROOT` and keep their own state in their own data directory. There is no registration: the files are readable by every process of the user, so the plugin can't know who reads them anyway. Disk use is bounded by retention (§5).

## 4. Event files

**Envelope**, one JSON document per file:

```json
{"v":1,"source":"claude-code","ts":1790000000,"pid":12345,"payload":{…hook JSON unchanged…}}
```

| Field | Meaning |
|---|---|
| `v` | Format version. Apps skip files with an unknown version. |
| `source` | Agent that produced the event, one of the registry below. Apps ignore sources they don't know. |
| `ts` | Unix seconds when the plugin saw the event. With async hooks this is not the exact moment of the event. |
| `pid` | The process that starts the hook (`$PPID` of the script), described per source in §6. Claude Code: the session's `claude` process. Codex without the daemon: the session's `codex` process; with it: a shared `app-server`, unsuitable for session liveness. |
| `payload` | The hook's stdin JSON, byte for byte. Apps parse the file as one JSON document, not line by line. |

Events with empty stdin are dropped.

**Sources:**

| `source` | Agent | Adapter | Root |
|---|---|---|---|
| `claude-code` | Claude Code | `adapters/claude-code/` | §2 |
| `codex` | Codex | `adapters/codex/` | §2 |

**Schema:** `$ROOT/schema/envelope.v<v>.json` is the JSON Schema (draft 2020-12, `$id` `urn:subspace:envelope:v1`) of an event file with that `v`. The plugin copies it from its own `schema/` on every `SessionStart`, so it always matches the installed version; the source is `schema/` in this repo (each adapter ships a copy), and CI validates the fixtures' envelopes against it. `v` is the reference: event files carry no `$schema` field. The schema pins the envelope; for the payload it only requires `hook_event_name`, because the payload's format belongs to the agent (its hooks reference, and the fixtures in `fixtures/<source>/<version>/`).

**Path:** `events/<UTC date YYYY-MM-DD>/<ts>-<pid>-<random>.json`. The name only serves uniqueness.

**Atomic write:** the plugin writes `.<name>.tmp` in the same folder and renames it to `<name>.json`. Apps never see a partial file if they ignore names starting with a dot.

**Permissions:** folders the plugin creates `0700`, files `0600`. The content is the agent's own hook payload; transcripts may contain additional data (§8).

## 5. Retention

- Claude Code: the user sets `retention_days` in `/config` (plugin `userConfig`, default 3, range 1–30). The hook script reads it as `CLAUDE_PLUGIN_OPTION_RETENTION_DAYS`. Codex has no corresponding plugin setting in 0.159.3 and keeps the default of 3; its adapter declares no `userConfig`.
- On every invocation the plugin deletes whole day folders older than `retention_days`: it keeps the current UTC day and the `retention_days` days before it, so at least `retention_days` × 24 hours of history remain. No per-file scanning, no size measuring.
- Apps must tolerate files and folders vanishing at any time, including while they read them.
- Apps don't delete anything. Longer history belongs in an app's own cache.

## 6. Consumer duties

- Resolve `$ROOT` as in §2. It may not exist yet (§3); wait for it to appear.
- Watch `events/` **recursively**; new day folders appear at UTC midnight and a session can span several of them.
- Read only `*.json`; ignore names starting with a dot.
- Never modify or delete event files. Track seen files yourself (on start, all existing files are the backlog of the last `retention_days` days).
- Skip unknown `v`, ignore unknown `hook_event_name`, skip and log unreadable files.
- Read payload values through the mapping document (§12) wherever a target field exists, instead of the agent's keys. The source-specific sections below name raw keys; their target fields are in `docs/model.md` §3–§4.
- **Don't trust arrival order.** Async hooks run in parallel, so e.g. a `PostToolUse` can arrive before its `PreToolUse`. Sort by file mtime (nanoseconds), then name, as a hint only, and correlate via IDs. IDs and lifecycle semantics are source-specific; use the sections below.

### Claude Code

- Correlate using:
  - `session_id`: the session, i.e. the orchestrator
  - `agent_id` / `agent_type`: present only inside a subagent, including on its tool calls; builds the tree
  - `tool_use_id`: pairs `PreToolUse` ↔ `PostToolUse` / `PostToolUseFailure`
  - `prompt_id`: the user prompt being processed
  - `PermissionRequest` has no `tool_use_id`; match it to the preceding `PreToolUse` via `session_id`/`agent_id` plus `tool_name`/`tool_input`
- **Subagent ↔ its `Agent` call:** `PreToolUse(Agent)` has `tool_use_id`, `tool_input.description` and `tool_input.prompt` but no `agent_id`; `SubagentStart` has `agent_id` but, in 2.1.285, no `tool_use_id`. Two subagents of the same type started in parallel can't be told apart by order (see above). Link them by the `Agent` call's `tool_use_id`, trying in this order:
  1. `parent_tool_use_id` on `SubagentStart`/`SubagentStop`. The hooks reference documents it (together with `description` on `SubagentStart`), but 2.1.285 doesn't send it yet. Use it when present.
  2. `toolUseId` in `<session>/subagents/agent-<agent_id>.meta.json`, where `<session>` is `transcript_path` without `.jsonl` (§8). Internal format: it may not exist yet when `SubagentStart` arrives, so retry briefly, and tolerate it missing.
  3. `tool_response.agentId` on `PostToolUse(Agent)`. Always there, but for foreground subagents only once they have finished; for background subagents right after the launch.

  The parent of a nested subagent is the `agent_id` on the `PreToolUse(Agent)` that spawned it (absent: the orchestrator). Until one of the three matches, show the subagent as unassigned.
- **Terminal states are sticky:** after `SubagentStop(A)` agent A is done, even if later events of A arrive; the same holds for `Stop` per turn and `SessionEnd` per session.
- **Background subagents:** in interactive sessions subagents may run in the background. Then `PostToolUse` for `Agent` arrives right after the launch, the orchestrator's `Stop` fires while they still run, and each result comes back as a `UserPromptSubmit` whose `prompt` starts with `<task-notification>` or, since 2.1.287, `<agent-message ` (after the subagent called the tool `SubagentHandback`); the user didn't type it. In 2.1.287 interactive `Agent` calls without `run_in_background` were launched in the background too. A subagent is done at its `SubagentStop`, never at `PostToolUse(Agent)`.
- **`background_tasks`** on `Stop` and `SubagentStop` is a snapshot of all running background agents (`id` = `agent_id`, `status`, `description`, `agent_type`) and background shells (`type: shell`). The target field `background_agents` (`docs/model.md` §3.2) lists the agent IDs. Apps can use it to correct their state.
- **Stopped background agents:** a background agent stopped by the user (Ctrl+X Ctrl+K, observed in 2.1.288) sends no `SubagentStop`, and its running tool no `PostToolUse`. It only disappears from the next snapshot. Apps end it there; the rules are in `docs/model.md` §3.3 ("Stopped background agents"). The turn that follows has the `prompt` `Background agent "<description>" was stopped by the user.`, which names no agent ID.
- **Session model:** `model` is in `SessionStart` only on an interactive `startup` and on `compact`; `/model` (and automatic switches) send `PostModelSwitch` with `to_model`. After `/clear`, on `--resume`/`--continue` and in `claude -p` sessions no hook names the session's model, and subspace has no other source for it: the session status file (§13) has no model field, nor does the hooks' environment (observed in 2.1.289). The model belongs to the process, not to the session:
  - **On `/clear` apps carry the model over.** The process keeps running with its current model (including an earlier `/model`) and sends `SessionEnd` (`reason: clear`) for the old and `SessionStart` (`source: clear`) for the new session, with the same envelope `pid`, within milliseconds and in either order. Apps assign the last known model of that `pid` (`SessionStart.model` or the latest `PostModelSwitch.to_model`) to the new session.
  - **On resume they don't.** A resumed session runs in a new process with that process's model, not the one the session had before. It stays unknown until a `PostModelSwitch` of the new process.
  - Rules and evidence: `docs/model.md` §3.3 ("Session model"). The transcript's `message.model` (§8) names the model of every response, for apps that read it.
- **Internal agents:** Claude Code runs agents of its own, e.g. for `/compact`. They send a `SubagentStop` with an empty `agent_type` and no `SubagentStart`, and their `agent_transcript_path` may not exist. Apps don't show them as subagents.
- **Liveness:** in the capture `SessionEnd` arrived async after `/exit` and after Ctrl-C (`reason: prompt_input_exit`) and at the end of `claude -p` (`reason: other`). It can still be missing after a crash or a killed terminal, so apps check `pid` and fall back to a timeout on the last event.
- **Working, waiting, interrupted:** a user interrupt (Esc, Ctrl-C) sends no hook event. The session status file (§13) shows it, and whether the session waits for the user; prefer it where present.

### Codex (CLI 0.159.3)

- **Session and turn identity:** child events retain the root `session_id`; `agent_id` identifies the child thread. Root events have no child identity. `turn_id` distinguishes turns; key a child turn by `session_id` + `agent_id` + `turn_id`, and a root turn by `session_id` + `turn_id`. Resume keeps the root `session_id` and `transcript_path`, with `SessionStart.source: resume`; compaction can yield `SessionStart.source: compact`.
- **Tool correlation:** pair `PreToolUse` and `PostToolUse` by `session_id`, optional `agent_id`, `turn_id` and `tool_use_id`. Captured tool names include `Bash` and `collaborationspawn_agent`. `PostToolUse.tool_response` for shell calls can contain stdout or be empty. The captured `exit 7` call has an empty response with no exit-code field; a post event alone does not prove success. Read its exit code from the rollout (§8).
- **Permission requests:** no `tool_use_id`. Match conservatively by session, child, turn, tool name and stable command fields. `PermissionRequest.tool_input` can add `description`, so whole-object equality is unsuitable. File arrival order is not request order. Concurrent identical requests can remain ambiguous. Remembered approvals can produce pre/post hooks with no permission event.
- **Child ↔ spawn correlation:** captured spawn responses are JSON encoded in `tool_response` strings and return task paths such as `/root/alpha`, not child UUIDs. The child's rollout `session_meta` supplies `id`, root `session_id`, `parent_thread_id`, and `source.subagent.thread_spawn.agent_path`. Link the returned task path to that metadata; never assign parallel children by arrival order. The [scenario 1 metadata excerpt](../fixtures/codex/0.159.3/1-headless-parallel-reused-child-failure/rollouts/session_meta.jsonl) and its unchanged hook payloads exercise this link (§8). Keep a child unassigned while its metadata is unavailable. Nested spawning and child reuse across resume were not observed.
- **Turn completion:** `SubagentStop` fires per child turn. A reused child has one start and multiple stops; a stop does not destroy the child thread. Completion is sticky for that particular turn, and a later turn can become active. `Stop` likewise completes a root turn, not the session.
- **Interrupt:** the user's confirmed permission action “Reject and tell Codex what to do instead” produced `Interrupt` with no post or `Stop` for that turn. This observation applies to that UI action. Interrupting a wait on a running shell call can leave the command running: a late `PostToolUse` arrived for the interrupted turn after the following turn's `Stop`. Do not reopen the interrupted turn on a late post, or infer process termination from `Interrupt`.
- **Session liveness:** there is no subscribed `SessionEnd`. Async work can be cancelled during teardown; final events may be lost. With the daemon, multiple sessions share the hook's `pid` (`app-server`); apps **must not use Codex `pid` to establish session liveness**. Use a timeout since the last event, tolerate missing terminal events, and label this as inferred inactivity. No timeout duration is imposed by this contract.

## 7. Subscribed events

The plugin subscribes to every event that provably only observes; the full list with reasons per source is in `docs/events/<source>.md` ([Claude Code](events/claude-code.md), [Codex](events/codex.md)). New observing events may be added at any time (§9).

**Never subscribed** for Claude Code, because registering them changes its behavior: `WorktreeCreate`, `WorktreeRemove`, `PreModelSwitch`. **Skipped** for now: `MessageDisplay`, `FileChanged`.

Codex subscribes to the eleven events listed in `docs/events/codex.md`, with `async: true` and no matcher. `SessionEnd` is never subscribed because Codex forces it to run synchronously; legacy `notify` is skipped and never modified.

## 8. Transcripts

### Claude Code

For Claude Code: token usage, model, timestamps and full responses are not in the hook payloads. They are in the transcript:

- `transcript_path` (every payload): the session's JSONL
- `agent_transcript_path` (`SubagentStop`): the subagent's JSONL under `<session>/subagents/`, next to an `agent-<id>.meta.json`. In the 2.1.285 capture every subagent had a meta file with `agentType`, `description`, `toolUseId`, `spawnDepth`, `requestShape` (`foreground`/`background`) and `requestNonInteractive` (see §6 for its use)

### Codex

- `transcript_path` references the current rollout, but is **null in ephemeral sessions**. Consumers must tolerate null, missing files, and lagging writes rather than constructing a substitute path.
- Captured child starts and tool events point to the child rollout. On `SubagentStop`, `transcript_path` points to the root rollout and `agent_transcript_path` to the child rollout. Prefer `agent_transcript_path` for the child's history.
- The captured rollout `session_meta` contains the child identity and parent/task-path link (§6). Token counts, full tool output and shell exit codes are in the rollouts, not guaranteed in hook responses. The internal JSONL contains session metadata, turn context, response items and event messages; use captured paths rather than assuming one filename format.
- Scenario 1 distributes an [edited `session_meta` excerpt](../fixtures/codex/0.159.3/1-headless-parallel-reused-child-failure/rollouts/session_meta.jsonl) from the root and both child rollouts for child-to-spawn correlation (§6). Only `payload.creator_user_id`, `payload.creator_account_id` and `payload.base_instructions.text` are replaced; all other bytes in those first lines remain as captured. The [fixture README](../fixtures/codex/0.159.3/README.md#edited-rollout-metadata-excerpt) documents the replacements. Full Codex rollouts are not shipped. The user's local rollout copies establish the additional findings documented in the fixture READMEs and `docs/events/codex.md`; hook payload fixtures remain unchanged.

Apps may read transcripts, read-only. Each agent's transcript format is internal and can change without notice; apps must degrade gracefully. The transcript is written asynchronously and may lag the hook events. subspace never touches transcripts.

## 9. Versioning

- Changes to the envelope or layout increase `v` and come with a new `schema/envelope.v<v>.json`. The plugin writes one version only.
- Subscribing to new events is backwards compatible; apps ignore unknown `hook_event_name`s.
- Mapping documents have their own `format` version and compatibility rules (§12). A new mapping arrives with a plugin release; it never changes `v`.

## 10. Platforms

Claude Code: macOS and Linux. On Windows, Claude Code runs hook scripts through Git Bash; without Git Bash it falls back to PowerShell and subspace does nothing.

Codex: observed on macOS 27.0 arm64 with CLI 0.159.3, including a project cwd containing spaces. Linux, WSL and native Windows are **unverified**. The adapter requires POSIX `sh` and standard utilities; Codex does not universally select Git Bash on native Windows. No native Windows support is claimed. A native binary replacing the script is planned for later; it would keep this contract unchanged.

## 11. Detecting subspace

Per source, apps distinguish installed/enabled from actual event delivery.

### Claude Code

**Is subspace installed and enabled?** Run `claude plugin list --json` and look for the entry with `"id": "subspace@subspace"`; it carries `enabled`, `version` and `scope`. The same CLI can offer the installation (`claude plugin marketplace add …`, `claude plugin install subspace@subspace --scope user`). Apps started from Finder or Dock don't inherit the shell's `PATH`, so they look for `claude` in the usual places (e.g. `~/.local/bin/claude`) or start it through a login shell. Only if `claude` can't be found, apps may fall back to reading `~/.claude/plugins/installed_plugins.json` and `enabledPlugins` in `~/.claude/settings.json`; both are internal to Claude Code and can change.

### Codex

Run `codex plugin list --json` and find the `installed` entry with `pluginId: "subspace@subspace"`, `marketplaceName: "subspace"`, `installed: true`, and `enabled: true`. Use the selected `CODEX_HOME` consistently with §2. Apps connected to the app-server can use `plugin/installed`. CLI discovery through a login shell may be needed for apps started from Finder/Dock, as with Claude Code.

Installation and enablement alone do not establish delivery: non-managed plugin hooks must be reviewed/trusted in `/hooks`, hooks may be disabled by effective configuration or policy, and changed hook definitions require another review. Installed-plugin tests on macOS confirmed retained trust for a version-only upgrade (0.0.0 → 0.0.1) and renewed trust for a changed SessionStart definition (0.0.2). These were disposable local packages, not published releases; see `tools/e2e/codex.md`.

Codex leaves data behind on uninstall, so the marker below can survive removal. Confirm CLI state separately.

**Updating needs the marketplace refreshed first:** `codex plugin marketplace upgrade subspace`, then `codex plugin add subspace@subspace`. Without the upgrade `add` reinstalls the version of the cached marketplace snapshot.

**After an update, restart Codex.** `codex plugin add` replaces the cached plugin version and deletes the previous one, so a session that keeps running across an update silently loses its hooks: no events, no fresh `plugin.json`, until Codex is restarted and a new session (not a resumed one) starts. Apps showing a stale `plugin.json` while `codex plugin list` reports a newer version can suggest a restart. Claude Code keeps older versions in its cache; an update takes effect with the next session.

### Actual delivery (both sources)

On every `SessionStart`, the plugin writes `$ROOT/plugin.json` (atomically, like event files):

```json
{"v":1,"version":"0.1.0"}
```

`version` is the plugin version from its `plugin.json`. The file's mtime is the last time subspace saw a session start. A disabled plugin leaves a stale file; an installed plugin that never ran leaves none.

## 12. Mapping documents

The payload is the agent's own format (§4) and changes with the agent. So that apps don't have to follow every change, subspace publishes one **mapping document** per source: where in the raw payload each **target field** is. Apps apply it when reading. Event files stay as they are; the mapping is a view on them.

- **Location:** `$ROOT/model/<source>.json`; Claude Code also ships `$ROOT/model/claude-code-session.json` for its session status files (§13), handled by the same rules. The plugin copies it from its own `model/` on every `SessionStart` (atomically, `0600`), so it always matches the installed release. It is missing until the first session start after installing a release that ships it, and it is older than the installed plugin until then. Apps therefore bundle a copy (the one their tests ran against) and use whichever of the two has the higher `revision`, among those whose `format` they know; on a tie, `$ROOT`'s.
- **Format and target fields:** [`docs/model.md`](model.md): the core fields (§2), the fields per source (§3, §4) and the rules (§5). Schemas: `$ROOT/schema/mapping.v1.json` (`$id` `urn:subspace:mapping:v1`) for the document, `$ROOT/schema/result.v1.json` for the result of applying it. Each root holds only its own source's result schema (`urn:subspace:result:claude-code:v1`, `urn:subspace:result:codex:v1`, since `claude-code-0.9.0`/`codex-0.4.0`; before that one shared `urn:subspace:result:v1` with both blocks), so a change for one source doesn't release the other's adapter. A `session-status.v1.json` left in a Codex root by `codex-0.3.0` is stale; ignore it.
- **Interpreter duties** (`docs/model.md` §5.1): an unknown `format` applies nothing; a rule or condition with an unknown key leaves that field absent; values are never guessed and copied unchanged; the interpreter never fails on a payload. Apps ignore unknown target fields, treat an unknown block `kind` like `unknown` and an unknown core `tool` like `other`.
- **Tests:** an app's interpreter must reproduce every golden file in `fixtures/<source>/<version>/<run>/expected/` from the raw payload next to it (`docs/model.md` §7). The reference interpreter is `tools/model/apply.py` (test tooling, never part of the hook).
- **A newer mapping applies to old events too.** A drift is absorbed by fallback paths, so older event files keep resolving. Results are derived data: an app that keeps them should expect a newer mapping to fill fields that were absent before.
- **Limits:** the mapping says where a value is, not what it means. New semantics (a new link field, an event that fires differently) still need app changes, announced here. The raw payload stays authoritative; anything without a target field is still read from it, at the cost of coupling to the agent's format.
- **Compatibility** (`docs/model.md` §6): new target fields, block kinds, table entries and core tool categories are compatible. Changing a target field's meaning or type is breaking and uses a new name. `format` increases only when the meaning of an existing rule key changes.

## 13. Side sources: Claude Code session status

Hooks don't say reliably whether a session is working: a user interrupt (Esc, Ctrl-C) sends no event (§6). Claude Code keeps this state itself, in one **session status file** per running process. Apps read it as a supplement to the event files. subspace never reads or writes it; this section and the mapping document are what subspace provides. The format is internal to Claude Code and undocumented: everything here comes from the captures in `fixtures/claude-code/2.1.287/` (Claude Code 2.1.287, macOS), see their README for the runs.

- **Path:** `<config dir>/sessions/<pid>.json`, where `<config dir>` is `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`, and `<pid>` is the `claude` process (the hooks' envelope `pid`). With `CLAUDE_CONFIG_DIR` set, `claude` created `sessions/` in that dir and nothing in `~/.claude/sessions/` (key file only: the capture had no login, so no `<pid>.json` yet). Read only `*.json`; the `<pid>.<hash>.key` files next to them are secrets and none of the apps' business.
- **Read only.** Never create, modify or delete anything in `sessions/`, also not stale files.
- **Reading:** through `$ROOT/model/claude-code-session.json` (§12; `docs/model.md` §12), which yields `session`, `cwd`, `state` (`working`, `waiting`, `idle`) and a block `claude_code_session` with `status`, `status_at`, `waiting_for`, `pid` and more; the result schema is `$ROOT/schema/session-status.v1.json`. Apps bundle a copy, as for §12.
- **Identity:** match it to the event files by `session` (`sessionId` = the hooks' `session_id`), **never by the file name**: one process can carry another session over time (`--continue`, `/clear`, `claude bg-spare`). On `/clear` the file switches to the new `sessionId` before the hooks' `SessionEnd`/`SessionStart` arrive (2.1.289).
- **What `state` means:** `working` while a turn runs, including background subagents (across their orchestrator's `Stop`s) and background shells; `waiting` while a permission dialog, a question or a dialog waits for the user (`waiting_for`); `idle` otherwise, also right after an interrupt. Unknown `status` values leave `state` absent.
- **Combining with the hooks:** the hooks stay the source for the session's structure (turns, tools, subagents). For "is it working", the newer of `status_at` and the latest event wins: an `idle` after the last `UserPromptSubmit` ends that turn although no `Stop` came.
- **Lifetime:** the file appears just before `SessionStart` (its first version has no `status` yet) and is deleted when the process ends normally (`/exit`, end of `claude -p`). After a crash it stays until the next `claude` process starts, so check that `pid` is alive before trusting a file.
- **Writes** are mostly in place, sometimes by rename. Watch the folder (FSEvents), re-read the changed file, and on unparseable content retry shortly instead of treating it as a change.
- **Fallback:** no file, an unreadable one or an absent `state` (older or newer Claude Code) → hooks and a timeout as before (§6).
- **Codex** has no equivalent file: its live state is held only in its app-server's memory, and connecting to it would change that server's behavior (CLI 0.160.0). Codex keeps hooks, `Interrupt` and a timeout (§6).
