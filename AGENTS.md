# subspace

Hooks for coding agents that **only observe**: every hook event is written as a file into a shared folder, one per agent (*source*), which consumer apps read. Sources today: **Claude Code** and **Codex**; more (e.g. Gemini CLI) may follow. Consumers today are **The Collective** ([`we-are-the-borg/collective`](https://github.com/we-are-the-borg/collective), Swift) and **Unimatrix Zero** ([`we-are-the-borg/unimatrix-zero`](https://github.com/we-are-the-borg/unimatrix-zero), Swift); both are native macOS apps.

These rules apply to every agent working in this repo. `CLAUDE.md` only imports this file.

- **Contract: `docs/contract.md`.** It is the interface to both apps. Every change to it is a change across three repos: mind `v` and keep the consumers in view.

## Layout

One development repository and one distribution repository per agent:

- **`we-are-the-borg/subspace`** (this one): development. Sources, tests, fixtures, docs, release-please. Not a marketplace.
- **`we-are-the-borg/subspace-<source>`** (`subspace-claude-code`, `subspace-codex`): that agent's plugin **at the repository root**, plus its marketplace file next to it (`.claude-plugin/marketplace.json` or `.agents/plugins/marketplace.json`, plugin source `"./"`), `README.md`, `docs/contract.md`, `docs/model.md` and `SOURCE` (the dev commit per tag). `main` only moves on releases, so installs only ever see released states; Anthropic's plugin directory can track it as is (a plugin in a subfolder would hold every version for a reviewer). **Written only by the release workflow** (`tools/dist/assemble.sh`); never edit or push them by hand. They may be re-created from scratch, see "Re-creating a dist repo" below.

In this repo:

- `adapters/<source>/`: one plugin per agent, shipped on its own as the root of its dist repo. `adapters/claude-code/`: `.claude-plugin/plugin.json` (version, `userConfig`), `hooks/hooks.json` (events from `docs/events/claude-code.md`, each calls `scripts/spool.sh claude-code`, the SessionStart hook with `session-start` added)
- `core/spool.sh`, `schema/*.json` (shared: envelope, mapping document), `schema/<source>/*.json` (that source only: mapping result, session status), `model/<source>.json`: the single sources of the hook script, the schemas and each source's mapping document (`docs/model.md`, contract §12). `adapters/*/scripts/spool.sh`, `adapters/*/schema/` and `adapters/<source>/model/` are copies: **never edit them**, run `sh tools/sync.sh`. CI fails on any difference
- `docs/model.md`: target fields and the mapping document format; `tools/model/apply.py` is the reference interpreter (test tooling only), `tests/model.test.py` checks every golden file (`fixtures/*/*/*/expected/`) and the interpreter rules
- `tools/dist/`: `assemble.sh <source> <dist tree> [<tag>]` rebuilds one adapter's dist repo from scratch (all but `.git` and `SOURCE`): the contents of `adapters/<source>/` exactly as committed (whatever the folder holds) at the root, the templates in `tools/dist/<source>/` (`README.md`, the marketplace file; marketplace names are frozen at `subspace`, see contract §2), `docs/contract.md`, `docs/model.md`, and a `SOURCE` line
- `release-please-config.json`, `.release-please-manifest.json`, `adapters/<source>/CHANGELOG.md` (written by release-please): releases, one release-please package per adapter (see Workflow)
- `.github/workflows/`: `ci` (tests, adapter copies in sync; assembles every dist repo without pushing and validates it: `claude plugin validate`, fixture envelopes against the schema), `pr-title` (Conventional Commits), `release-please` (release PRs and the `dist` job that publishes to `we-are-the-borg/subspace-<source>`)
- `tests/spool.test.sh`: tests for `spool.sh` as shipped (`sh tests/spool.test.sh`, `SPOOL_SH=dash` to run the script under another shell)
- `fixtures/<source>/<version>/`: real, curated hook payloads both apps test against, anonymized (`fixtures/README.md`); `tests/fixtures-privacy.test.py` guards the whole repository
- `docs/events/<source>.md`: which hook events are subscribed, never subscribed or skipped, and why
- `tools/sync.sh`: copies `core/`, the shared `schema/*.json` plus `schema/<source>/` and each adapter's `model/<source>*.json` into the adapters. Keep source-specific things out of the shared files: every change to them releases every adapter
- `tools/e2e/check.sh`: checks a day folder of a real install against the contract and the fixtures' payload keys (Claude Code)
- `tools/hook-capture/<source>/`: throwaway project that records the subscribed hook events under `captures/` (source of the fixtures). Claude Code also records the session status files (`watch-sessions.py`) and has a driver that plays the runs in a pseudo-terminal (`drive-session-runs.py`)

## Rules

- **Never steer:** every hook runs async wherever the agent allows it, every script exits 0 and writes nothing to stdout or stderr. No hook may return decision fields or anything the agent reads as context.
- **No runtime dependencies** in the hook script: POSIX `sh` and standard utilities only, no `node`, `jq` or `python`.
- **Pass raw data only:** the payload is kept byte for byte. All interpretation happens in the apps, guided by the mapping documents (`model/`), which subspace ships but never applies in the hook.
- **No hooks that replace behavior.** See `docs/events/<source>.md`. Before subscribing to a new event, check in the agent's hooks reference (or source) that registering it alone changes nothing, and record the result there.
- **Agent-neutral core:** `core/spool.sh` knows no agent; the source comes as its argument (the SessionStart hook adds `session-start`). Agent specifics live in the adapter and in the contract's per-source sections.
- Don't write into repos, into an agent's configuration, or outside `$ROOT` (the adapter's plugin data directory, see contract §2).
- **Agent drift** (contract §12, `docs/model.md` §6): capture the new version into `fixtures/<source>/<version>/`, add its golden files, then change only `model/<source>.json` (fallback paths, table entries, new fields; never drop a path older captures need) until `python3 tests/model.test.py` passes, increase its `revision` (CI checks it), add the version to `observed`, release. New semantics also need a contract note for the apps.
- **No personal data in the repository.** Anonymize every capture before it goes into `fixtures/` as `fixtures/README.md` describes (home paths, remotes, account identifiers, content of files read from the user's machine; no full transcripts) and run `python3 tests/fixtures-privacy.test.py`. The repository is public.
- Derive assumptions about payloads only from real captures. Claude Code captures: agents may run `tools/hook-capture/claude-code/drive-session-runs.py` (real sessions, haiku, a few cents) and extend it with new runs. Other captures the user starts themselves (`codex exec` …).

## Workflow

- Never commit directly to `main`: branch → PR → squash merge.
- **PR titles follow Conventional Commits** (`feat:`, `fix:`, `docs:`, `chore:` …; `!` for breaking). The squash commit takes the PR title, and release-please derives version and changelog from it. Use the scope `contract` (`feat(contract): …`) for changes the apps must know about.
- **Never bump versions by hand.** Each adapter is its own release-please package with its own version, changelog and tag (`claude-code-0.6.0`, no `v`). Only commits that touch `adapters/<source>/` release that adapter; a change to `core/` or `schema/` reaches the adapters through their synced copies. release-please keeps a release PR open that bumps the adapter's manifest version and its `CHANGELOG.md`; merging it tags the release here. Edit the changelog in that PR if needed.
- **Publishing:** the same workflow run then publishes every released adapter to its dist repo `we-are-the-borg/subspace-<source>` (job `dist`, one matrix entry per tag). Tags pushed with `GITHUB_TOKEN` trigger no other workflow, so the job is gated on release-please's outputs (`paths_released`, `<path>--release_created`, `<path>--tag_name`). It checks out this repo at the tag, runs `tools/dist/assemble.sh`, and pushes one commit `release: <tag>` plus the tag with `git push --atomic`. All writes (release PRs, tags, dist pushes) use tokens of the org's release GitHub App (`actions/create-github-app-token`; variable `RELEASE_APP_CLIENT_ID`, secret `RELEASE_APP_PRIVATE_KEY`; installed on this repo and every dist repo with Contents and Pull requests: read and write), so release PRs run CI and no deploy keys are needed. Tags already in the dist repo are skipped; re-run with `workflow_dispatch` and the tag (the tag must contain this `tools/dist/assemble.sh`).
- **New adapter:** add a package in `release-please-config.json` (`component` = source) with `extra-files` for its manifest's `$.version`; templates in `tools/dist/<source>/` (`README.md` and the agent's marketplace file, plugin source `"./"`); a repo `we-are-the-borg/subspace-<source>` with the release GitHub App installed on it.
- **Re-creating a dist repo** (so its history doesn't grow forever): pick the versions still supported; for each of their tags, in release order, run `sh tools/dist/assemble.sh <source> <new dist tree> <tag>` in a worktree of this repo at that tag (copy the current `tools/dist/` into it if the tag predates it), commit (`release: <tag>`) and tag it; then force-push `main` and push those tags to `we-are-the-borg/subspace-<source>`, deleting the others. A one-time manual push is the only exception to "never push by hand" and needs the user's go. Codex re-clones on `marketplace upgrade`; Claude Code may need `marketplace remove` + `add` once.
- Each adapter's first release from this repository is 1.0.0 (`initial-version`), the go-live release. From then on SemVer applies: a breaking change (`!`, e.g. to the contract) bumps the major version.
- Everything in the repo is English: code, comments, commits, README, plan and contract. Conversation with the user may be German.
