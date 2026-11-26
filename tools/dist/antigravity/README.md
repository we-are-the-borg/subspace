# subspace for Antigravity

Observe-only hooks for Google Antigravity (`agy` CLI and Antigravity desktop App). On every subscribed hook event the plugin writes the event, unchanged, as one JSON file into a local folder, so local apps such as [The Collective](https://github.com/we-are-the-borg/collective) and [Unimatrix Zero](https://github.com/we-are-the-borg/unimatrix-zero) can show what Antigravity and its subagents are doing.

## What it does

- Runs one POSIX `sh` script (`scripts/spool.sh`) as a command hook on all six lifecycle events (`SessionStart`, `PreInvocation`, `PostInvocation`, `PreToolUse`, `PostToolUse`, `Stop`). Antigravity runs hooks synchronously; the script always exits 0, prints nothing and returns no decision, so it never steers Antigravity.
- Writes only into its plugin data folder (`$PLUGIN_DATA`): `~/.gemini/antigravity-cli/plugin_data/subspace/` for the CLI, `~/.gemini/antigravity/plugin_data/subspace/` for the desktop App. Each event lands in `events/<UTC day>/` with the hook payload as Antigravity passed it, including prompts and tool inputs. Next to it, it stores your terminal or app identifiers (a fixed list of variables such as `TERM_PROGRAM`, `WARP_FOCUS_URL` or `__CFBundleIdentifier`, so apps can bring your terminal or Antigravity window to the front) and never anything else from the environment.
- Keeps events for 3 days and deletes older day folders while hooks run.
- Sends nothing anywhere: no network access, no other files read or written, no runtime dependencies.

`agy plugin uninstall subspace` (CLI 1.5.17) also deletes both data folders and with them the events. Removing the plugin folder by hand (see below) keeps them; delete them yourself.

## Install

With the `agy` CLI:

```sh
agy plugin install https://github.com/we-are-the-borg/subspace-antigravity
```

Without `agy` (for example with only the desktop App), clone this repository into Antigravity's plugin folder:

```sh
git clone --depth 1 https://github.com/we-are-the-borg/subspace-antigravity.git ~/.gemini/config/plugins/subspace
```

Then quit Antigravity (⌘Q), start it again and begin a new conversation. Antigravity loads every plugin in that folder; no other configuration is needed. Enable or disable it in the App under Customizations › Installed.

## Update

With the `agy` CLI:

```sh
agy plugin install https://github.com/we-are-the-borg/subspace-antigravity
```

Without `agy`:

```sh
git -C ~/.gemini/config/plugins/subspace pull --ff-only
```

Then restart Antigravity as after installing. `main` of this repository always holds the latest release, one commit per release, so the pull is a fast-forward.

## Uninstall

```sh
agy plugin uninstall subspace
```

Without `agy`, quit Antigravity and delete `~/.gemini/config/plugins/subspace`.

## Privacy

Everything stays on your computer; nothing is sent anywhere. Details: [Privacy policy](https://github.com/we-are-the-borg/subspace/blob/main/PRIVACY.md).

## For apps

The folder layout, file format and detection rules are in [`docs/contract.md`](docs/contract.md); the mapping documents in `model/` are described in [`docs/model.md`](docs/model.md). This repository holds only what the plugin installs and is written by the release workflow of [`we-are-the-borg/subspace`](https://github.com/we-are-the-borg/subspace), where development happens. `SOURCE` names the development commit each release was built from.
