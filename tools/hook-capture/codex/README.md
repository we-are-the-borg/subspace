# Codex hook capture

Targets `codex-cli 0.159.3`. This throwaway project records the eleven events from the
[subscribe list](../../../docs/events/codex.md#subscribe): command handlers,
`async: true`, no matcher, no output, exit 0. It registers no `SessionEnd`,
installs no plugin and leaves `notify` alone. Only the user starts these runs.

`log.sh` saves stdin byte for byte as `captures/events/<name>.json`, using an
atomic rename. Its matching `.meta` records `$PPID`, the full process ancestry
through PID 1 (`pid`, `ppid`, `comm`, `args` with `ps -ww` requesting wide output),
exported `CODEX_*`,
`PLUGIN_*` and `CLAUDE_*` **names**, `$SHELL` and `$0`. A single `ps` snapshot
keeps this fast for `Interrupt`'s 1-second timeout. If an ancestor is inaccessible
or vanishes, metadata says `unavailable pid=…`; do not treat that as PID evidence.
The payload is published before diagnostics, so cancellation can leave a JSON
without its metadata. Record such gaps rather than inferring a parent PID.

`collect.sh` is a manually started offline helper requiring Python 3. It copies
every non-null `transcript_path` **and** `agent_transcript_path` from the captured
JSON, including child threads. It does not assume Claude's `subagents/` layout or
scan unrelated sessions. Copies go to `captures/transcripts/<path digest>/`, with
`source.txt` identifying the original path. Missing rollouts and invalid JSON
are reported, other copies continue, and the helper returns 1. Re-run it after
rollouts have flushed; null/ephemeral paths are expected evidence, not invented
transcripts. The hook itself uses POSIX sh and common Unix utilities (`mktemp`,
`ps`, `awk`, etc.), with no Python. Process arguments remain subject to host OS
limitations.

## Preparation

Start from the repository root, then stay in this directory for runs 1–5:

```sh
cd tools/hook-capture/codex
mkdir -p captures/runs
codex --version > captures/version.txt
codex
```

1. Accept the project trust dialog if offered. Open `/hooks`, find this project's
   `.codex/hooks.json`, review and enable/trust its eleven definitions. Verify no
   `SessionEnd` definition comes from this file. Installing files alone does not
   trust hooks. Do not bypass hook trust for these captures.
2. Exit with `/exit`, restart `codex`, send `Reply with capture-ready.`, and check
   that `captures/events/` now contains `SessionStart` and `UserPromptSubmit`.
   Trusting hooks after startup cannot recover an earlier skipped event. If no
   files appear, check `/hooks` and project trust before continuing.
3. Finish with `/exit`. Keep preparation events; note them in
   `captures/runs/notes.md` along with OS, CLI version, run order, root session IDs,
   whether the CLI attached to the shared daemon or fell back to embedded mode,
   approvals/denials, UI warnings, missing events and unavailable capabilities.
   Collect after each run: `sh ./collect.sh`.

The commands below were checked against `codex --help`, `codex exec --help` and
`codex resume --help`, not executed as captures. Positional prompts precede
options. Do not use `/cd`, `--worktree`, another `-C`, or change a child's working
directory: the logger command is `sh ./log.sh`, relative to the event's cwd.
Multi-agent support is enabled by default in this version. Avoid `--enable`/`-c`
feature overrides in the daemon run: some force an embedded fallback.

**Why a nested project works:** the pinned loader walks from the repository root
to the starting cwd and includes each `.codex/` directory, even without a
`config.toml`; hook discovery reads `hooks.json` beside those enabled layers.
Starting from the repository root does not descend into this capture project.
[Project-layer discovery](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/config/src/loader/mod.rs#L1586-L1754),
[hook discovery](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/discovery.rs#L118-L187).
Project trust and definition trust are separate requirements.
[Project trust](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/config/src/loader/mod.rs#L1086-L1103),
[hook trust](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks).
Hooks run at the event cwd; children inherit their parent's turn cwd.
[Runner](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/hooks/src/engine/command_runner.rs#L214-L226),
[child config](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/core/src/agent/child_config.rs#L167-L193).

## 1. Headless: tools, failure, parallel and nested children

Answers open questions **1, 2, 4, 5, 8**.

```sh
codex exec 'This is a read-only capture workload. Keep every thread in the current working directory; do not edit project files. Run pwd, then run sh -c "exit 7" exactly once and report the failure without retrying. Start exactly two subagents concurrently and wait for both: alpha must run printf "alpha\\n" using its shell tool; beta must read README.md using a tool, then if supported spawn one nested child that runs pwd and wait for it. After both finish, send alpha one follow-up asking it to run printf "alpha-again\\n" and wait for its reply. If nested spawning or child reuse is unavailable, report that explicitly. Return the results and child IDs.' \
  --sandbox read-only --json > captures/runs/1-headless.jsonl
sh ./collect.sh
```

This checks pre/post pairing, failed-command coverage (Codex has no subscribed
`PostToolUseFailure`), concurrent starts, a nested parent link, child tool calls,
reuse across turns and actual rollout paths. A missing late `Stop` may reflect
async cancellation at teardown. Retain the CLI JSONL to compare calls, timestamps
and token metadata with files; do not derive fixtures from an imagined schema.
`codex exec` is in-process and defaults to approval policy `never`, so permission
dialogs and the daemon comparison belong to interactive runs.
[Exec approval policy](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/exec/src/lib.rs#L571-L580).

## 2. Interactive shared daemon: approvals, compaction, normal exit

Answers open questions **1, 2, 3, 4, 5, 8**.

```sh
codex -a on-request -s read-only
```

Open `/status` and record the `Server` row: this version labels a local daemon
connection `Local background server`. If it is absent, record the embedded
fallback; that run does not establish daemon PID behavior. Avoid automatic
approval (`--approve-for-me`) for this manual-permission run.
[Status evidence](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/tui/src/status/card.rs#L797-L812).

`-a on-request` controls when a request is made; `approvals_reviewer` separately
controls who reviews it. An inherited `auto_review` setting can approve these
commands without showing a dialog, even without `--approve-for-me`. Record that
as automatic-review coverage and use supplemental run 2b for manual decisions.
Keep this daemon run free of `-c` overrides, which can force embedded mode.
[Reviewer setting](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/config/src/config_toml.rs#L190-L197),
[daemon exclusion](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/tui/src/daemon_startup.rs#L54-L87).

1. Send the same workload as run 1 (the text inside the outer single quotes).
2. Send: `Run printf 'permission-approved\n' > captures/permission-probe in the
   shell. This disposable write needs elevated sandbox permission because the
   session is read-only; request it and wait for my approval. Do not retry or
   modify any other files.` When the permission dialog appears,
   approve **once**, without remembering a rule. Note its time and the tool shown.
3. Send: `Run printf 'permission-denied\n' > captures/permission-denied-probe in
   the shell. Request elevated sandbox permission for this disposable write and
   wait for my approval. If denied, report it without retrying, substituting a
   tool or modifying files.` Deny **once** and
   note what Codex does. If policy auto-approves/denies or the model never requests
   elevation, record that outcome; it is not a manual approval capture.
4. Repeat the approved command and choose a remembered approval if the UI offers
   it; repeat it once more. This checks whether hooks appear again for remembered
   permissions. If that option is absent, record it. No hook decides the result.
5. Enter `/compact`, wait for completion, then send `Read README.md with a tool
   and report its first heading.` Record `PreCompact`, `PostCompact`, any
   `SessionStart` and their source/turn fields; do not assume all arrive.
6. After the response finishes, enter `/exit`, then run `sh ./collect.sh` and
   remove the probes with `rm -f captures/permission-probe captures/permission-denied-probe`.

Normal exit is deliberately covered without `SessionEnd`: check queued `Stop`
delivery and inspect the captured host PID after exit. The daemon can remain
alive independently of this session. `/compact` and `/exit` are supported slash
commands in the pinned version.
[Slash commands](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/tui/src/slash_command.rs).

### 2b. Supplemental manual approval and denial

Use this when run 2 had no manual permission dialogs. It completes open question
3; the original daemon capture remains useful. From this capture directory:

```sh
codex --no-daemon -a on-request -s read-only -c 'approvals_reviewer="user"'
```

The reviewer value `user` explicitly routes requests to you for this invocation;
no personal configuration edit is needed. Embedded mode is explicit because
this version excludes this `-c` override from daemon attachment.
[Reviewer values](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/protocol/src/config_types.rs#L175-L196).

1. Send: `Run printf 'manual-approved\n' > captures/manual-permission-approved-probe
   in the shell. Request elevated sandbox permission for this disposable write
   and wait for my approval. Do not retry or modify any other files.` Approve
   once without remembering a rule.
2. Send: `Run printf 'manual-denied\n' > captures/manual-permission-denied-probe
   in the shell. Request elevated sandbox permission and wait for my approval.
   If denied, report it without retrying, substituting a tool or modifying
   files.` Deny once. Use these fresh names so file existence can confirm whether
   the commands actually executed; the denied probe should remain absent.
3. For remembered approvals, repeat the approved command, choose the remembered
   option if offered, then repeat once more. Record an absent option. If the
   requests still never reach you, stop this scenario and record the policy/UI
   outcome instead of counting it as manual approval coverage.
4. Finish with `/exit`, then `sh ./collect.sh`. Keep the probes until their
   presence/absence has been checked and the notes updated.

## 3. Interactive without daemon: interrupt and normal exit

Answers open questions **1, 2, 5, 7, 8**; compare `.meta` with run 2.

```sh
codex --no-daemon -a on-request -s read-only
```

1. Send `Use the shell tool to run sleep 30, then report done. Do not edit files.`
   Press Ctrl-C **while the turn/tool is running**, once, to interrupt the turn.
   Note whether `Interrupt` arrives and whether the shell command was cancelled.
2. Send `Run pwd with the shell tool and report its output.` Wait for the response,
   then `/exit`. Collect with `sh ./collect.sh`.
3. Start the same command again, interrupt another `sleep 30` turn, and immediately
   exit using the UI's Ctrl-C exit gesture. Record the number of presses and
   whether this immediate shutdown loses the async `Interrupt`. Collect again.

Use `/status` to record that this run has no `Local background server` connection.

The first case lets an interrupted turn settle before shutdown; the second
checks the cancellation boundary. Compare the complete parent chains, `$PPID`,
shell/argv0 and environment names between daemon and embedded runs. Do not call
an outer shell or shared host PID a session-liveness PID without evidence.

## 4. Resume the interactive root session

Answers open questions **1, 2, 4, 8**.

Copy the **root** `session_id` from run 2 into the command below, replacing
`ROOT_SESSION_ID` (do not use a child's ID):

```sh
codex resume ROOT_SESSION_ID -a on-request -s read-only
```

Send `Run pwd using the shell tool. If the prior alpha child is still reusable,
send it a follow-up to run pwd and wait for it; otherwise report that it is not
reusable. Do not edit files.` Finish with `/exit`, then `sh ./collect.sh`.
Check `SessionStart`'s resume source, identity continuity, new turn/tool IDs,
child start/stop coverage and whether the referenced rollout changed.

## 5. Ephemeral headless session

Answers open questions **1, 2, 8**, especially null or missing transcript paths.

```sh
codex exec 'Run pwd using the shell tool and report it. Do not edit files or start subagents.' \
  --ephemeral --sandbox read-only --json > captures/runs/5-ephemeral.jsonl
sh ./collect.sh
```

Keep missing/null-path observations. The collector cannot reconstruct an
ephemeral or cancelled rollout and should not search personal sessions for one.

## 6. Path with spaces and platform/shell repeat

Answers open questions **1, 2, 5, 7, 8**. Run this on each available macOS, Linux,
WSL and native-Windows installation; record unavailable platforms explicitly.

From the capture directory, create a second working directory under the ignored
tree. It inherits the existing ancestor `.codex/hooks.json`; **do not copy that
file**, which would register duplicate hooks.

```sh
mkdir -p 'captures/project with spaces'
cp log.sh collect.sh README.md 'captures/project with spaces/'
cd 'captures/project with spaces'
codex --no-daemon -a on-request -s read-only
```

Review inherited hooks in `/hooks` if prompted. Send `Run pwd with the shell tool
and report its output. Do not edit files.`, then interrupt a `sleep 30` turn and
finish with `/exit`. Run `sh ./collect.sh` here; this run's payloads and transcript
copies live in its own nested `captures/`. Check `.meta` for the actual outer
shell and script path, compare stdin bytes with the ordinary-path runs, and note
startup messages or hook errors. These are shell-style commands; on native
Windows, prepare the same files with the host shell and inspect whether Codex's
chosen outer shell can invoke `sh`. If POSIX utilities are unavailable, record the
unsupported result rather than introducing a different logging implementation.
Plugin paths containing spaces are covered by the installed-plugin test
(`tools/e2e/codex.md`).

## Coverage and handoff

| Question | Runs / evidence |
|---|---|
| 1: delivery across modes, failure, denial, interrupt, exit, resume, compact | 1–5; 2 normal daemon exit, 3 settled vs immediate interrupt shutdown |
| 2: raw bytes, fields, tool coverage and outer vs nested/parallel calls | 1–6; retain CLI JSONL, try a read-only MCP/code-mode tool if already available and record absence otherwise |
| 3: manual/remembered approvals, denials, request correlation | 2 and supplemental 2b if inherited auto-review handled requests; note dialogs, retries and reviewer behavior |
| 4: concurrent/nested children, reused child turns and transcript paths | 1, 2, 4 |
| 5: host PID with/without shared daemon | 2 vs 3; complete `.meta` chains, 1 as headless comparison |
| 6: plugin data path, custom `CODEX_HOME`, re-trust, uninstall | Installed-plugin test (`tools/e2e/codex.md`) |
| 7: shell startup, silence, byte preservation, paths with spaces, cancellation | 3, 6 on each available platform; plugin-specific paths in the installed-plugin test |
| 8: rollout format, token metadata, parent links, delayed/null paths | 1–6, collect after exit and again if files were delayed; 5 ephemeral |

Do not clear captures between runs: async events can arrive out of order. Use
root session IDs and your notes to separate scenarios. All `captures/` trees are
git-ignored. Return the complete outer `captures/` directory (including the
space-path run), with notes and collected transcripts, for curation into
`fixtures/codex/<version>/<n>-<scenario>/`. Synthetic tests are not fixtures:

```sh
python3 ../../../tests/codex-capture.test.py
```

Payload conclusions, adapter and contract changes follow from the curated
fixtures, not from raw captures.
