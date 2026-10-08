# subspace for Claude Code

Observe-only hooks for Claude Code. On every subscribed hook event the plugin writes the event, unchanged, as one JSON file into a local folder, so local apps such as [The Collective](https://github.com/we-are-the-borg/collective) and [Unimatrix Zero](https://github.com/we-are-the-borg/unimatrix-zero) can show what Claude Code and its subagents are doing.

The plugin consists of hooks only, so it works in Claude Code (terminal, IDE and desktop app on your machine). Enabled on claude.ai or in Cowork, it does nothing there.

## What it does

- Runs one POSIX `sh` script (`scripts/spool.sh`) as an `async` command hook. It always exits 0, prints nothing and returns no decision, so it never blocks or steers Claude Code.
- Writes only into its plugin data folder: `~/.claude/plugins/data/subspace-subspace/` (or under `$CLAUDE_CONFIG_DIR`). Each event lands in `events/<UTC day>/` with the hook payload as Claude Code passed it, including prompts, tool input and tool output.
- Keeps events for 3 days by default and deletes older day folders (`retention_days`, 1–30, see [Settings](#settings)).
- Sends nothing anywhere: no network access, no other files read or written, no runtime dependencies.

## Install

```sh
claude plugin marketplace add we-are-the-borg/subspace-claude-code
claude plugin install subspace@subspace --scope user
```

The install may report that a `userConfig` option is not set yet: that is `retention_days`, which defaults to 3 days. Install only one copy of subspace; two enabled copies would write every event twice.

## Settings

`retention_days` (1–30, default 3) sets how many days of events are kept. Set it in Claude Code under `/plugin` → Installed → subspace → Configure options, from your shell with `claude plugin configure subspace@subspace`, or when installing with `--config retention_days=7`.

## Update

```sh
claude plugin update subspace@subspace --scope user
```

The new version takes effect with the next session, or after `/reload-plugins`. Claude Code doesn't update plugins from this marketplace on its own; to change that, open `/plugin` → Marketplaces → subspace → Enable auto-update.

## Uninstall

```sh
claude plugin uninstall subspace@subspace --scope user
```

This deletes the data folder and all events in it; add `--keep-data` to keep them.

## Privacy

Everything stays on your computer; nothing is sent anywhere. Details: [Privacy policy](https://github.com/we-are-the-borg/subspace/blob/main/PRIVACY.md).

## For apps

The folder layout, file format and detection rules are in [`docs/contract.md`](docs/contract.md); the mapping documents in `model/` are described in [`docs/model.md`](docs/model.md). This repository holds only what the plugin installs and is written by the release workflow of [`we-are-the-borg/subspace`](https://github.com/we-are-the-borg/subspace), where development happens. `SOURCE` names the development commit each release was built from.
