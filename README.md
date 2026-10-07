# subspace

Observe-only hooks for coding agents. Every hook event is written, unchanged, as a file into a shared folder that local apps read, so local apps can show what coding agents and their subagents are doing without touching the agents themselves.

Agents: **Claude Code** (`adapters/claude-code/`) and **Codex** (`adapters/codex/`, CLI 0.159.3). Codex was verified with a locally installed plugin on macOS; others such as Gemini CLI can follow as further adapters.

Consumers today: **The Collective** and **Unimatrix Zero**.

- Hooks run `async` and always exit 0: subspace never blocks or steers an agent.
- No runtime dependencies – the hook script is plain POSIX `sh`, shared by all adapters (`core/spool.sh`).
- Apps only read; events are kept for three days by default (configurable in Claude Code). See [`docs/contract.md`](docs/contract.md).

**This repository is for development.** Each agent's plugin installs from its own distribution repository, which is also its marketplace and is written only by the release workflow: [`we-are-the-borg/subspace-claude-code`](https://github.com/we-are-the-borg/subspace-claude-code) and [`we-are-the-borg/subspace-codex`](https://github.com/we-are-the-borg/subspace-codex).

## Install

### Claude Code

```sh
claude plugin marketplace add we-are-the-borg/subspace-claude-code
claude plugin install subspace@subspace --scope user
```

Events land in `~/.claude/plugins/data/subspace-subspace/`, or under
`$CLAUDE_CONFIG_DIR/plugins/data/subspace-subspace/` when configured. Set
`retention_days` in the plugin's `/config` settings (default 3, range 1–30).

### Codex

The Codex adapter uses its own `.codex-plugin/plugin.json` and marketplace
catalog at `.agents/plugins/marketplace.json` in `we-are-the-borg/subspace-codex`, so Codex installs the Codex
adapter. Review and trust its eleven async hooks in `/hooks` after installation.
The shared writer uses Codex's supplied plugin-data compatibility variable.
See [the pinned research and observed findings](docs/events/codex.md) and
[OpenAI's plugin packaging guide](https://developers.openai.com/plugins/build/plugins).

To install the working tree locally instead, use the
[local installed-plugin verification procedure](tools/e2e/codex.md).

```sh
codex plugin marketplace add we-are-the-borg/subspace-codex
codex plugin add subspace@subspace
codex plugin list --marketplace subspace --json
```

Events land in `~/.codex/plugins/data/subspace-subspace/`, or under
`$CODEX_HOME/plugins/data/subspace-subspace/`. Retention stays at three days;
Codex 0.159.3 exposes no corresponding plugin option. Hooks run in the
background, but async events can be lost during shutdown. There is no subscribed
`SessionEnd`; apps infer inactivity using a timeout since the last event.

To update, refresh the marketplace and install its current release:

```sh
codex plugin marketplace upgrade subspace
codex plugin add subspace@subspace
```

Review `/hooks` after an update: changed definitions can require renewed trust.
Check `codex plugin list --json` for installed/enabled state; a marker file alone
does not establish either, because Codex preserves data on uninstall.

```sh
codex plugin remove subspace@subspace
```

Stop sessions using the plugin first. Uninstall removes registration/cache and
keeps the data root; users can explicitly delete that resolved root if they
want to purge the retained events. Claude Code instead removes its data root on
uninstall.

Codex captures cover macOS, including a project cwd with spaces. Linux, WSL and
native Windows remain unverified; this adapter requires POSIX `sh` and standard
utilities.
