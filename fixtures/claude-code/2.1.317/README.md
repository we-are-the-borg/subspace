# Fixtures: Claude Code 2.1.317

Recorded on macOS on 2026-11-03 with `tools/hook-capture/claude-code/drive-session-runs.py S21`, in a Warp tab (Warp `v0.2026.10.07.08.29.stable_00`). There are no payloads and no golden files: this capture only checks the environment the hooks run in (contract §4, "Terminal identifiers").

## Runs

| Run | What happened |
|---|---|
| `21-terminal-env` | Haiku, interactive, started from a shell in Warp. One prompt without tools, `/exit`. `log.sh` recorded the allowlisted variables of every hook (`SessionStart`, two `InstructionsLoaded`, `UserPromptSubmit`, `Stop`, `SessionEnd`). `terminal.json` is the `terminal` field that the shipped `scripts/spool.sh` writes for that environment. |

## Findings

- Claude Code passes the terminal variables to its hooks **unchanged**. All six hooks saw exactly the values of the shell `claude` was started from: no name was added, dropped or rewritten.
- Warp sets `TERM_PROGRAM`, `TERM_PROGRAM_VERSION`, `__CFBundleIdentifier` (`dev.warp.Warp-Stable`), `WARP_FOCUS_URL` and `WARP_TERMINAL_SESSION_UUID`. The session ID is 32 hex digits without dashes, and the focus URL is `warp://session/<that ID>`.
- `TERM_SESSION_ID`, `ITERM_SESSION_ID`, `TMUX` and the rest are not set in Warp.
- Not captured yet: other terminals, tmux, and Codex with and without the daemon (#22).
