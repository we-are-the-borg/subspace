# subspace

subspace lets desktop apps follow your coding agents while they work.

It currently connects **Claude Code** and **Codex** to
[The Collective](https://github.com/we-are-the-borg/collective) and
[Unimatrix Zero](https://github.com/we-are-the-borg/unimatrix-zero).
Each plugin saves the agent's hook events to a local folder. The apps read
those files to keep track of sessions, tool calls and subagents.

The events contain the same kinds of session data the agents already write
to disk. subspace keeps the payloads unchanged and ships mappings that let
the apps read them in a consistent format.

When an agent update renames or moves fields, an updated mapping can keep
the apps working without an app update. Keep the subspace plugin up to date
to get those fixes.

The hooks run in the background. They don't give the agent instructions or
make decisions for it. Both plugins use the same small shell script and
require only POSIX `sh` and standard utilities. Your agent data will
stay on your machine. subspace doesn't send it anywhere.

## Install

### Claude Code

```sh
claude plugin marketplace add we-are-the-borg/subspace-claude-code
claude plugin install subspace@subspace --scope user
```

The plugin works in Claude Code. It isn't available in claude.ai or Cowork.

To update:

```sh
claude plugin update subspace@subspace
```

You can also enable automatic updates under `/plugin` → Marketplaces.

### Codex

```sh
codex plugin marketplace add we-are-the-borg/subspace-codex
codex plugin add subspace@subspace
```

After installing, open `/hooks` to review and trust the hooks.

To update:

```sh
codex plugin marketplace upgrade subspace
codex plugin add subspace@subspace
```

Restart Codex after updating. If the hook definitions have changed, review
them again in `/hooks`.

The Codex adapter has been tested with CLI 0.159.3 on macOS.
Linux, WSL and native Windows have not been verified.

## What gets stored

subspace saves the hook payloads as it receives them. These can include your
prompts, tool inputs and tool outputs, so the event files may contain
sensitive information. They stay on your machine; subspace doesn't send
them anywhere.

The default locations are:

| Agent       | Event data                                  |
| ----------- | ------------------------------------------- |
| Claude Code | `~/.claude/plugins/data/subspace-subspace/` |
| Codex       | `~/.codex/plugins/data/subspace-subspace/`  |

If you use `CLAUDE_CONFIG_DIR` or `CODEX_HOME`, the data lives under that
directory instead.

Cleanup runs whenever a hook runs. By default, it keeps the current UTC
day and the three preceding days.

In Claude Code, you can change `retention_days` to a value from 1 to 30
under `/plugin` → Installed → subspace → Configure options, or run:

```sh
claude plugin configure subspace@subspace
```

Codex currently uses the fixed default.

## Uninstall

For Claude Code:

```sh
claude plugin uninstall subspace@subspace --scope user
```

Claude Code also removes the plugin's data folder.

For Codex:

```sh
codex plugin remove subspace@subspace
```

Stop sessions using the plugin before uninstalling. Codex leaves the data
folder behind; delete it separately if you want to remove the saved events.

## About this repository and me

I build subspace with help from Claude Code and Codex.
I review everything the agents write and test the code before releasing it.

To borrow a line from the agents: I can make mistakes.
You're welcome to read the code, question a decision or point out a bug.

## Building an app or contributing

This is the development repository. Releases are published to
[subspace-claude-code](https://github.com/we-are-the-borg/subspace-claude-code)
and [subspace-codex](https://github.com/we-are-the-borg/subspace-codex),
where each plugin has its own marketplace.

Start with the [contract](docs/contract.md) for the folder layout, event
format and rules for reading the data. The [mapping documents](docs/model.md)
describe how to extract fields from each agent's payloads.

Hook delivery has limits. For example, Codex can lose background events
during shutdown, so apps can't rely on receiving a final event.
The [Claude Code](docs/events/claude-code.md) and
[Codex](docs/events/codex.md) event notes document what we've observed.

To test the Codex plugin from a local checkout, follow the
[local installation guide](tools/e2e/codex.md).

## License

[MIT](LICENSE)
