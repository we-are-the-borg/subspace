# subspace for Claude Code

Observe-only hooks for Claude Code. On every subscribed hook event the plugin writes the event, unchanged, as one JSON file into a local folder, so local apps such as [The Collective](https://github.com/we-are-the-borg/collective) and [Unimatrix Zero](https://github.com/we-are-the-borg/unimatrix-zero) can show what Claude Code and its subagents are doing.

## What it does

- Runs one POSIX `sh` script (`scripts/spool.sh`) as an `async` command hook. It always exits 0, prints nothing and returns no decision, so it never blocks or steers Claude Code.
- Writes only into its plugin data folder: `~/.claude/plugins/data/subspace-subspace/` (or under `$CLAUDE_CONFIG_DIR`). Each event lands in `events/<UTC day>/` with the hook payload as Claude Code passed it, including prompts, tool input and tool output.
- Keeps events for 3 days by default (`retention_days`, 1–30, in the plugin's `/config` settings) and deletes older day folders.
- Sends nothing anywhere: no network access, no other files read or written, no runtime dependencies.

Claude Code deletes the data folder when the plugin is uninstalled.

## Install

```sh
claude plugin marketplace add we-are-the-borg/subspace-claude-code
claude plugin install subspace@subspace --scope user
```

## Update

```sh
claude plugin update subspace@subspace --scope user
```

The new version takes effect with the next session, or after `/reload-plugins`.

## Uninstall

```sh
claude plugin uninstall subspace@subspace --scope user
```

## For apps

The folder layout, file format and detection rules are in [`docs/contract.md`](docs/contract.md); the mapping documents in `model/` are described in [`docs/model.md`](docs/model.md). This repository holds only what the plugin installs and is written by the release workflow of [`we-are-the-borg/subspace`](https://github.com/we-are-the-borg/subspace), where development happens. `SOURCE` names the development commit each release was built from.
