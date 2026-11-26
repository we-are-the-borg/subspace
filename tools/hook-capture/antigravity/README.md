# Antigravity hook capture

Targets Antigravity CLI `agy 1.5.15`, Antigravity App (2.0) and Antigravity IDE.
This throwaway project records all six lifecycle events documented in
[`docs/events/antigravity.md`](../../../docs/events/antigravity.md) via
`.agents/hooks.json`: `SessionStart`, `PreToolUse`, `PostToolUse`,
`PreInvocation`, `PostInvocation` and `Stop`. Handlers are synchronous `command`
hooks (Antigravity has no `async` mode), silent (empty stdout and stderr) and
always exit 0. Only the user starts these runs.

`log.sh` saves stdin byte for byte as `captures/events/<name>.json` using an
atomic rename. Its matching `.meta` records `ts`, `$PPID`, `pwd` (the hook
process's working directory, to verify whether Antigravity runs hooks in
`.agents/` or the workspace root), `$SHELL`, `$0`, the full process ancestry
through PID 1 (`pid`, `ppid`, `comm`, `args` with `ps -ww`), exported `AGY_*`,
`ANTIGRAVITY_*`, `GEMINI_*`, `GOOGLE_*`, `PLUGIN_*` and `CLAUDE_*` **names** (no
values), and the allowlisted terminal identifiers from contract §4. The
`.agents/hooks.json` command tries `../log.sh` first and falls back to
`./log.sh`, so it works whether Antigravity sets hook `cwd` to `.agents/` or the
workspace root.

`collect.sh` is a manually started offline helper requiring Python 3. It copies
every non-empty `transcriptPath` (plus defensive subagent/snake_case fallbacks
if present) from `captures/events/*.json` into
`captures/transcripts/<path digest>/<basename>`, with `source.txt` keeping the
original path so multiple `transcript.jsonl` files never overwrite one another.
Missing transcripts, relative paths and invalid JSON are reported to stderr,
other copies continue, and the helper returns 1. Re-run it after transcripts
have flushed. The hook itself uses POSIX `sh` and standard Unix utilities only,
with no Python.

## Preparation

Start from the repository root, then stay in this directory for runs 1–5:

```sh
cd tools/hook-capture/antigravity
mkdir -p captures/runs
agy --version > captures/version.txt
```

1. **Smoke test (empty stdout vs. `{}` check):** start `agy`, send
   `Reply with capture-ready. Do not call any tools.`, wait for the answer, then
   exit (`/exit` or `Ctrl+D Ctrl+D`).
2. Inspect `captures/events/` and `captures/events/*.meta`:
   - Confirm `SessionStart`, `PreInvocation`, `PostInvocation` and `Stop` files
     landed and check `pwd`, `ppid`, process chain, `env names` and `terminal`.
   - Record any UI warnings, hook errors or altered behavior in
     `captures/runs/notes.md` (along with OS, `agy --version`, surface, model,
     run order and `conversationId`s).
   - Run `sh ./collect.sh` and confirm whether `transcriptPath` exists and is
     populated.
3. **Optional `{}` stdout comparison probe:** if empty stdout triggers hook
   errors, parse warnings, or blocks/alters `PreToolUse` or `Stop`, record the
   exact failure first, then run a temporary isolated test (without committing
   changes to `.agents/hooks.json`) where the command ends with
   `&& printf '{}\n'` (or tests a single event at a time) and note whether `{}`
   clears the warning or changes `PreToolUse` decisions.

Do not change directories inside prompts: keep every run in this directory
except run 7 (path with spaces).

## 1. Headless CLI (`agy -p`): tools, failure, subagent, JSON stream

Answers open questions **1, 2, 3, 5, 6, 7**.

```sh
agy -p 'This is a read-only capture workload. Keep every action in the current working directory; do not edit project files. First run pwd using run_command, then run sh -c "exit 7" exactly once and report the failure without retrying. Next, if invoke_subagent is available, launch one read-only subagent that replies with "sub-ok" without editing files and wait for it; otherwise report that subagents are unavailable. Return the results.' \
  --sandbox --output-format stream-json > captures/runs/1-headless.jsonl
sh ./collect.sh
```

Checks:
- Whether `SessionStart`, `PreInvocation`, `PreToolUse`, `PostToolUse`,
  `PostInvocation` and `Stop` all fire and finish before `-p` exits.
- Raw camelCase fields (`hookEventName`, `conversationId`, `toolCall.id`/`.name`/`.args`,
  `stepIdx`, `error` on the failing `exit 7` command, `modelName`, `cwd`).
- Whether `PostToolUse` contains stdout/output or only `error`.
- Whether `transcriptPath` is populated in `-p` mode.
- Compare the hook payloads and `.meta` timestamps with `1-headless.jsonl`.

## 2. Interactive CLI (`agy`): `PreToolUse` "Never steer" matrix & normal exit

Answers open questions **1, 2, 3, 5, 7**.

First run **with** `.agents/hooks.json` active (using your normal/default policy,
or explicit `--mode` / `--sandbox` noted in `captures/runs/notes.md`):

```sh
agy --sandbox
```

1. **Auto-allowed tool:** send `Read README.md and report its first heading. Do
   not edit files.` Note whether any unexpected permission dialog appeared.
2. **Command requiring approval (approve once):** send `Run printf
   'permission-approved\n' > captures/permission-probe using run_command. If it
   asks for permission, wait for my approval. Do not retry or modify other
   files.` Approve once (without "Always Allow") and note:
   - Did a permission dialog still appear (proving silent `PreToolUse` did not
     auto-approve)?
   - Did `PreToolUse` fire before or after the dialog (check `.meta` `ts` vs.
     wall-clock approval time)?
3. **Command requiring approval (deny once):** send `Run printf
   'permission-denied\n' > captures/permission-denied-probe using run_command.
   If denied, report the denial without retrying or editing files.` Deny once
   and check whether `PostToolUse` fires for the denied call, whether
   `captures/permission-denied-probe` stayed absent, and how `Stop` ends the
   turn.
4. **Model / effort check (optional):** if you switch model or pass `--effort`
   (e.g. `agy --effort high` in a short follow-up), note whether `modelName`
   changes in payloads and whether effort appears in payloads or transcripts.
5. Exit with `/exit` (or `Ctrl+D Ctrl+D`), run `sh ./collect.sh`, and clean up
   with `rm -f captures/permission-probe captures/permission-denied-probe`.
6. **Baseline comparison (critical for Q1):** temporarily disable `PreToolUse`
   (e.g. remove only `PreToolUse` or set `"enabled": false` in a throwaway copy,
   then restore `.agents/hooks.json` before committing) and repeat steps 1–3
   with fresh probe names. Confirm that the approval/auto-proceed behavior is
   identical with and without `PreToolUse` registered.

## 3. Interactive CLI: user interrupt (`Esc` / `Ctrl-C`) & background command

Answers open questions **2, 3, 6**.

```sh
agy --sandbox
```

1. Send `Use run_command to run sleep 30, then reply done. Do not edit files.`
   Interrupt mid-tool (`Esc` or `Ctrl-C`). Record which key you pressed, whether
   `PostToolUse` arrived, and the exact `Stop.terminationReason` (expected
   `USER_CANCELED`?).
2. Send `Run pwd with run_command and report it.` Wait for completion.
3. If background commands are supported, start a short background command
   (`sleep 15` with backgrounding) and ask the agent to reply immediately before
   it finishes; check `Stop.fullyIdle` (`false` vs. `true`).
4. Exit with `/exit` and run `sh ./collect.sh`.

## 4. Resume an interactive session (`--continue` / `--conversation`)

Answers open questions **2, 3, 7**.

Copy the `conversationId` from run 2 and resume it:

```sh
agy --conversation CONVERSATION_ID --sandbox
```

(Or `agy --continue --sandbox` right after run 2.)

Send `Run pwd with run_command and report it. Do not edit files.` Wait for the
answer, exit with `/exit`, and run `sh ./collect.sh`.

Check:
- Does `SessionStart` fire on resume?
- Are `conversationId` and `transcriptPath` identical to run 2?
- Do `invocationNum`, `stepIdx` and `executionNum` reset or continue?

## 5. Subagents (parallel & foreground/background)

Answers open questions **2, 6, 7**.

```sh
agy --sandbox
```

Send: `This is a read-only capture workload. Launch exactly two subagents in
parallel using invoke_subagent: subagent 1 should run pwd and reply with the
result; subagent 2 should read README.md and reply with its first heading. Wait
for both and reply with their results. Do not edit files.`

Wait until both subagents and the parent turn finish, exit with `/exit`, and
run `sh ./collect.sh`.

Check:
- How `PreToolUse` and `PostToolUse` represent `invoke_subagent` (`toolCall.name`,
  `toolCall.args`, `toolCall.id`).
- Whether hooks fire inside the subagents at all, and if so, whether their
  `conversationId` and `transcriptPath` match the parent or belong to the child.
- Whether the parent transcript (and any child transcripts) link parent and
  child conversation IDs.

## 6. Desktop App (Antigravity 2.0) and IDE (`antigravity-ide`)

Answers open questions **2, 3, 5, 7**.

Open `tools/hook-capture/antigravity` as the project/workspace in **Antigravity
App** (and in **Antigravity IDE** if installed):

1. Start a new conversation and send `Read README.md and run pwd with
   run_command, then reply with both. Do not edit files.`
2. Note the wall-clock time and surface in `captures/runs/notes.md`.
3. Optionally start a second conversation in the same App window to compare
   `$PPID` and the process chain in `.meta` across two sessions.
4. Run `sh ./collect.sh` afterwards.

Compare across CLI (`antigravity-cli/`), App (`antigravity/`) and IDE
(`antigravity-ide/`):
- `transcriptPath` and `artifactDirectoryPath` locations and transcript format.
- `$PPID` and ancestor chain (per-session process vs. shared host/Electron
  process).
- `terminal:` entries in `.meta`.
- Any payload differences (e.g. `modelName`, `cwd`, `workspacePaths`).

## 7. Path with spaces

Answers open questions **2, 8**.

Create a working directory with spaces under the ignored `captures/` tree. It
inherits the ancestor `.agents/hooks.json`; **do not copy `.agents/hooks.json`**
(which would register duplicate hooks).

```sh
mkdir -p 'captures/project with spaces'
cp log.sh collect.sh README.md 'captures/project with spaces/'
cd 'captures/project with spaces'
agy --sandbox
```

Send `Run pwd with run_command and report its output. Do not edit files.`, then
`/exit`. Check whether events landed in the outer `captures/events/` (hook ran
in ancestor `.agents/`) or in `captures/project with spaces/captures/events/`
(hook ran in workspace root), run `sh ./collect.sh` where the events landed, and
verify `pwd`, `argv0` and raw stdin bytes.

## 8. Installed plugin, `PLUGIN_DATA` path and uninstall probe

Answers open question **4** (and informs Phase 3 packaging).

Build a disposable local plugin outside the repo (e.g. in a temp folder) with
`.antigravity-plugin/plugin.json`, root `hooks.json` (calling a copy of `log.sh`
that also records `PLUGIN_ROOT` and `PLUGIN_DATA` values to a scratch file, not
committed), validate it, install it, run one prompt, and uninstall it:

```sh
probe=$(mktemp -d)
mkdir -p "$probe/.antigravity-plugin" "$probe/scripts"
cat > "$probe/.antigravity-plugin/plugin.json" <<'EOF'
{
  "name": "subspace-probe",
  "version": "0.0.1",
  "description": "Disposable local probe for subspace capture"
}
EOF
cat > "$probe/hooks.json" <<'EOF'
{
  "subspace-probe": {
    "SessionStart": [{"type": "command", "command": "sh ./scripts/probe.sh"}],
    "Stop": [{"type": "command", "command": "sh ./scripts/probe.sh"}]
  }
}
EOF
cat > "$probe/scripts/probe.sh" <<'EOF'
#!/bin/sh
{
  umask 077
  out="${PLUGIN_DATA:-/tmp}/probe.meta"
  [ -n "${PLUGIN_DATA:-}" ] && mkdir -p "$PLUGIN_DATA"
  printf 'ts=%s\npwd=%s\nPLUGIN_ROOT=%s\nPLUGIN_DATA=%s\nCLAUDE_PLUGIN_DATA=%s\n' \
    "$(date +%s)" "$(pwd)" "${PLUGIN_ROOT-unset}" "${PLUGIN_DATA-unset}" \
    "${CLAUDE_PLUGIN_DATA-unset}" >> "$out"
} > /dev/null 2>&1
exit 0
EOF
chmod +x "$probe/scripts/probe.sh"
agy plugin validate --strict --json "$probe"
agy plugin install "$probe"
agy plugin list --json > captures/runs/8-plugin-list.json
```

1. Run a short prompt in `agy` (and optionally in the App) to trigger
   `SessionStart` and `Stop`.
2. Record the exact `PLUGIN_ROOT`, `PLUGIN_DATA`, `CLAUDE_PLUGIN_DATA` and `pwd`
   written to `probe.meta`, and check `config.json` for where enablement is
   stored.
3. Run `agy plugin uninstall subspace-probe` and check whether the `PLUGIN_DATA`
   directory was deleted or kept. Remove any leftover `PLUGIN_DATA` probe folder
   and `rm -rf "$probe"`.

## Coverage and handoff

| Question (`docs/events/antigravity.md`) | Runs / evidence |
|---|---|
| 1: `PreToolUse` "Never steer" & empty stdout vs. `{}` | Preparation smoke test + optional `{}` probe; Run 2 (with vs. without `PreToolUse`) |
| 2: Raw camelCase payloads, `hookEventName`, `PostToolUse` error/output, `pwd` | Runs 1–7 |
| 3: Firing semantics (`SessionStart` on resume/`-p`, `Pre`/`PostInvocation`, `Stop` reasons, surfaces) | Runs 1, 2, 3, 4, 6 |
| 4: Plugin packaging, `PLUGIN_DATA`, `agy plugin list --json`, uninstall | Run 8 |
| 5: `$PPID`, full process ancestry & `terminal` env vars across surfaces | Runs 1, 2, 6 (`.meta` chains) |
| 6: Subagents (`invoke_subagent`) & background tasks (`fullyIdle`) | Runs 1, 3, 5 |
| 7: Transcript format, flush timing & `artifactDirectoryPath` across surfaces | Runs 1–6 + `collect.sh` |
| 8: Platforms, shells, synchronous latency & paths with spaces | Runs 1–7 (especially Run 7) |

Do not clear `captures/` between runs; use `conversationId` and
`captures/runs/notes.md` to separate scenarios. All `captures/` trees are
git-ignored. Return the complete `captures/` directory (including notes and
collected transcripts) for curation into `fixtures/antigravity/<version>/`.
Synthetic tests are not fixtures:

```sh
python3 ../../../tests/antigravity-capture.test.py
```

Payload conclusions, `envelope.v1.json` decisions, adapter and contract changes
follow from curated fixtures, not from raw captures.
