# subspace for Codex

Observe-only hooks for the Codex CLI. On every subscribed hook event the plugin writes the event, unchanged, as one JSON file into a local folder, so local apps such as [The Collective](https://github.com/we-are-the-borg/collective) and [Unimatrix Zero](https://github.com/we-are-the-borg/unimatrix-zero) can show what Codex and its child agents are doing.

## What it does

- Runs one POSIX `sh` script (`scripts/spool.sh`) as an `async` command hook on eleven lifecycle events (no `SessionEnd`, which Codex runs synchronously). It always exits 0, prints nothing and returns no decision, so it never blocks or steers Codex.
- Writes only into its plugin data folder: `~/.codex/plugins/data/subspace-subspace/` (or under `$CODEX_HOME`). Each event lands in `events/<UTC day>/` with the hook payload as Codex passed it, including prompts, tool input and tool output.
- Keeps events for 3 days and deletes older day folders while hooks run.
- Sends nothing anywhere: no network access, no other files read or written, no runtime dependencies.

Codex keeps the data folder after uninstall; delete it yourself to remove the events.

## Install

```sh
codex plugin marketplace add we-are-the-borg/subspace-codex
codex plugin add subspace@subspace
```

Then review and trust the hooks in `/hooks`.

## Update

```sh
codex plugin marketplace upgrade subspace
codex plugin add subspace@subspace
```

Restart Codex afterwards: a running session loses its hooks when the old version is removed. Changed hook definitions need renewed trust in `/hooks`.

## Uninstall

```sh
codex plugin remove subspace@subspace
```

## Privacy

Everything stays on your computer; nothing is sent anywhere. Details: [Privacy policy](https://github.com/we-are-the-borg/subspace/blob/main/PRIVACY.md).

## For apps

The folder layout, file format and detection rules are in [`docs/contract.md`](docs/contract.md); the mapping documents in `model/` are described in [`docs/model.md`](docs/model.md). This repository holds only what the plugin installs and is written by the release workflow of [`we-are-the-borg/subspace`](https://github.com/we-are-the-borg/subspace), where development happens. `SOURCE` names the development commit each release was built from.
