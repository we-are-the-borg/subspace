# Privacy

subspace is a plugin for coding agents (Claude Code, Codex) that runs entirely on your own computer. This policy covers the plugins published from this repository: `we-are-the-borg/subspace-claude-code` and `we-are-the-borg/subspace-codex`.

## What the plugin processes

On every subscribed hook event, the agent passes the event's data to the plugin's hook script. That data can include your prompts, the agent's tool calls with their input and output (for example file contents and command output), file paths, session identifiers and the path to the agent's transcript. It can therefore contain personal data, depending on what you work on.

The plugin also records which terminal the agent runs in: a fixed list of environment variables that terminals set to identify their app, tab or pane (for example `TERM_PROGRAM`, `ITERM_SESSION_ID`, `WARP_FOCUS_URL`, `TMUX_PANE`). It stores no other environment variables, so tokens or other secrets in your environment are never stored.

## Where it goes

- The plugin writes each event, unchanged, as a file into its plugin data folder on your computer (`~/.claude/plugins/data/subspace-subspace/` for Claude Code, `~/.codex/plugins/data/subspace-subspace/` for Codex, or the equivalent under `CLAUDE_CONFIG_DIR` / `CODEX_HOME`). Files and folders are readable by your user account only.
- Nothing is sent anywhere. The plugin has no network access, no telemetry, no analytics and no update checks of its own. Neither the author nor anyone else receives any data from it.
- Local apps you install yourself (such as The Collective or Unimatrix Zero) may read these files. What they do with them is covered by their own documentation.

## How long it is kept

The plugin deletes events older than the retention period: 3 days by default. In Claude Code you can set it from 1 to 30 days (`retention_days`); Codex always uses 3 days. Claude Code deletes the data folder when you uninstall the plugin (unless you pass `--keep-data`); Codex keeps it, and you can delete the folder yourself at any time.

## The agents themselves

Claude Code and Codex process your data under their own terms and privacy policies (Anthropic, OpenAI). The plugin does not change what they collect or send.

## Contact

Questions about this policy: open an issue at <https://github.com/we-are-the-borg/subspace/issues>. For security problems see [`SECURITY.md`](SECURITY.md).
