# Hook capture

Throwaway Claude Code project that records every subscribed hook event (see `docs/events/claude-code.md`) under the same conditions as the real plugin: `async: true`, no output, exit 0.

- `log.sh` writes one file per event to `captures/events/`: `<name>.json` is the raw payload, `<name>.meta` holds `$PPID`, `$CLAUDE_PID`, the parent process chain and the names (not values) of exported `CLAUDE_*` variables.
- `collect.sh` copies every transcript the events reference, including `subagents/`, to `captures/transcripts/`.

`captures/` is git-ignored; curated payloads go to `fixtures/claude-code/<version>/`.

## Runs

Run everything from this directory. Start clean with `rm -rf captures`.

**1. Headless, two parallel subagents**

```sh
claude -p "Start exactly two general-purpose subagents in parallel (one message, two Agent calls). Agent 1: 'Run: sleep 3; echo alpha. Report the output.' Agent 2: 'Read README.md and report its content.' Then reply with both results." \
  --model haiku --allowedTools "Agent" "Bash(sleep 3; echo alpha)" "Read"
```

The prompt must come right after `-p`: `--allowedTools` takes any number of values and would swallow it. `-p` also kills async hooks still running at teardown, so late events such as `Stop` or `SessionEnd` may be missing here. Run 2 covers them.

**2. Interactive, ended with `/exit`**

Start `claude --model haiku`. On the first start, accept the workspace trust dialog, otherwise the project hooks don't run.

1. Send the same prompt as in run 1, without the quotes around it.
2. When a permission prompt appears, **wait at least 10 seconds** before approving (the `permission_prompt` notification fires after about 6 s).
3. Run `/compact`.
4. Run `/model sonnet`.
5. Run `/exit`.

**3. Interactive, ended with Ctrl-C**

Start `claude --model haiku`, send `hi`, wait for the answer, then press Ctrl-C twice.

**Afterwards**

```sh
./collect.sh
```

## Session status file

Claude Code keeps one status file per process in `<config dir>/sessions/<pid>.json` (`status` `busy`/`idle`/…). `watch-sessions.py` records it next to the hook events: every change of content or inode as a snapshot in `captures/sessions/NNNNNN-<pid>.json`, every observation (created, changed, deleted, other names such as temp files) in `captures/sessions/log.jsonl` with wall-clock ms. Only files whose `cwd` lies in this directory are recorded; `*.key` files are never read.

**Automated:** `./drive-session-runs.py [S1 …]` plays S1–S18 below without a human. It starts the watcher, drives `claude` in a pseudo-terminal (prompts, Enter, Esc, Ctrl-C, Ctrl+X Ctrl+K, `kill -9`), waits for the hook events (never for the status file under test), logs every action with wall-clock ms to `captures/sessions/actions.jsonl` and each run's terminal output to `captures/tty/<run>.log`, and runs `collect.sh` at the end. It answers the startup dialog "Allow external CLAUDE.md file imports?" (the repo's `CLAUDE.md` imports `AGENTS.md`, outside this directory) with its default "No"; any other dialog makes the run fail. About 10 minutes, haiku.

**By hand:** start the watcher in a **second terminal**, before `claude` and from this directory, and stop it with Ctrl-C a few seconds after the last run ended. A hook can't start it: the file appears before `SessionStart` and vanishes after it. One watcher covers all runs below.

```sh
./watch-sessions.py
```

Runs, each in the first terminal from this directory with `claude --model haiku`. Write down the wall-clock time of every action (`date +%T` in a third terminal is enough) in `captures/notes.md`.

- **S1 idle and exit:** send `hi`, wait for the answer, wait 5 s, `/exit`.
- **S2 interrupt mid-turn:** send `Write a 600-word story about a lighthouse.` and press Esc while it streams. Wait 5 s, send it again and press Ctrl-C once while it streams. Wait 5 s, `/exit`.
- **S3 interrupt mid-tool:** start with `--allowedTools "Bash(sleep 20; echo done)"`, send `Run exactly: sleep 20; echo done` and press Esc during the sleep. Wait 5 s, `/exit`.
- **S4 waiting for the user:** send `Run exactly: touch captures/perm-one` (`echo` needs no permission). Wait 15 s at the permission dialog, then approve. Send `Run exactly: touch captures/perm-two`, wait 15 s, reject. Send `Use the AskUserQuestion tool to ask me which color I like, with two options.` Wait 15 s, then answer. `/exit`.
- **S5 shell:** type `! sleep 10`, wait until it ends, `/exit`.
- **S6 subagents:** send `Start one general-purpose subagent in the foreground: 'Run: sleep 10; echo fg. Report the output.' Then reply with its result.` and approve the commands. Then send `Start one general-purpose subagent in the background: 'Run: sleep 30; echo bg. Report the output.' Don't wait for it.` Wait until its result came in plus 5 s, `/exit`.
- **S7 resume:** `claude --model haiku --continue`, send `hi`, wait for the answer, `/exit`.
- **S8 crash:** start `claude --model haiku`, send `hi`, wait for the answer. In another terminal `kill -9 <pid>` (the pid is the snapshot's file name). Wait 10 s. Then start S9: does a new process clean up the stale file?
- **S9 headless:** `claude -p "hi" --model haiku`.
- **S10 `CLAUDE_CONFIG_DIR`:** start a second watcher with `CLAUDE_CONFIG_DIR=<fresh dir> WATCH_SESSIONS_OUT=captures/sessions-s10 ./watch-sessions.py`, then `CLAUDE_CONFIG_DIR=<fresh dir> claude --model haiku`; without a login it stops at onboarding. After 20 s look at `<fresh dir>/sessions/` and `~/.claude/sessions/`, then quit. Delete `<fresh dir>` afterwards (it holds a key file).
- **S11 exit without prompt:** start, wait 5 s, `/exit`.
- **S12 failing tool:** start with `--allowedTools "Bash(ls captures/nonexistent-dir)"`, send `Run exactly: ls captures/nonexistent-dir`, approve if asked, `/exit`.
- **S13 file tools:** start with `--allowedTools Write Edit Read Grep Glob`, have it write `captures/s13.txt`, edit, read, grep and glob it, `/exit`.
- **S14 terminated before any input:** start, wait 5 s, `kill -TERM <pid>`.
- **S15 stopped background agent:** start with `--model sonnet --allowedTools Agent "Bash(sleep 10; echo one)"` (and `two`, `three`, `four`), send `Call the Agent tool once with subagent_type general-purpose and run_in_background true, prompt: 'Run these Bash commands one after the other, each in the foreground: sleep 10; echo one, then sleep 10; echo two, then sleep 10; echo three, then sleep 10; echo four. Report the output.' Don't wait for it.` After its `Stop`, wait 5 s and press Ctrl+X Ctrl+K twice (stops all background agents). Wait 5 s, send `Reply with the word ok. No tools.`, wait 60 s after its answer, `/exit`.
- **S16 subagent model:** start with `--model sonnet --allowedTools Agent`, send `Call the Agent tool twice in one message. First call: subagent_type general-purpose, model haiku, prompt 'Reply with the word one. No tools.' Second call: subagent_type general-purpose, no model parameter, prompt 'Reply with the word two. No tools.' Then reply with both results.` Wait for both subagents' `SubagentStop`, 20 s more for the hand-back turns, `/exit`.
- **S17 `/model`, then `/clear`:** send `Reply with the word one. No tools.`, then `/model sonnet` and confirm "Switch model?" with its default (Yes), then `/clear`, then `Reply with the word two. No tools.`, `/exit`. **`/model` saves `sonnet` as your default model in `~/.claude/settings.json`; reset it afterwards.**
- **S18 resume with another model:** right after S17, `claude --model haiku --continue`, send `Reply with the word three. No tools.`, `/exit`. The transcripts (`message.model`) show which model answered.

Afterwards `./collect.sh` as usual.

Questions: which `status` values appear (`waiting`? `shell`?) and when; does Esc/Ctrl-C switch to `idle` without any hook; does `statusUpdatedAt` match the action times; is the file replaced atomically (`inode_changed` in `log.jsonl`, temp names as `other`); is it deleted on `/exit`, after `-p`, after `kill -9`; does a resumed session get a new file; does `sessionId` change within one pid.

## What the captures check

- Do tool calls inside a subagent carry its `agent_id`? Which fields do `Agent` tool calls and `SubagentStart`/`SubagentStop` have?
- Is `$PPID` the Claude process (compare with the process chain in `.meta`)? Is `CLAUDE_PID` set in hooks and does it match?
- Does `SessionEnd` arrive async after `/exit` (run 2) and Ctrl-C (run 3)?
- How far does arrival order (file mtime) deviate from the transcript timestamps?
- Payload sizes, especially outliers.
