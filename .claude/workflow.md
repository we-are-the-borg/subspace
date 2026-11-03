# Workflow profile

## Repo

The root of this repository (`git rev-parse --show-toplevel`), GitHub `we-are-the-borg/subspace`.

Everything in this repo is English: code, comments, docs, issues, plans, PR texts.

## Read first

- `AGENTS.md`: the rules. They win over everything else.
- `tasks/lessons.md` and `tasks/todo.md`, if present (local, git-ignored). If the ticket is part of a plan there, that plan's order and decisions apply.
- `docs/contract.md`: the sections the ticket touches. It is the interface to the consumer apps (The Collective, Unimatrix Zero).
- `docs/model.md`: if the ticket touches mapping documents (`model/`) or target fields.
- `docs/events/<source>.md`: if the ticket touches subscribed events.
- `fixtures/<source>/<version>/README.md`: the captures the ticket relies on.

## Open questions

`on`. Subspace issues name the section `## Open` or `## Open questions`. Unticked proposal items that say "decide" or "discuss" are open questions too.

## Plan

- **Entry points** in the sources only: `core/`, `schema/`, `model/`. Never point at the copies under `adapters/*/scripts|schema|model/`; `tools/sync.sh` writes them.
- **Decomposition:** contract text and the code that implements it go into the same task or into dependent tasks, never into independent ones.
- **Captures:** which real payloads prove the behavior (`fixtures/<source>/<version>/`)? Assumptions about payloads come from captures only.
  - Claude Code: an implementer may capture with `tools/hook-capture/claude-code/drive-session-runs.py` (real sessions, haiku, a few cents); new runs are added there.
  - Codex: the maintainer starts the captures. If one is missing, say so; never invent it.
- **Contract impact:** does the ticket change `docs/contract.md`, a schema or a mapping document? If so:
  - Does it touch `v` (contract §9)?
  - Is it `feat(contract)`, and is it breaking (`!`)?
  - What must The Collective and Unimatrix Zero know or verify?

  A contract decision is the maintainer's. If the ticket doesn't settle it, it is an open question.
- **Release impact:** which adapters release, and as patch, minor or major?
  - Only commits that touch `adapters/<source>/` release that adapter, including the synced copies.
  - A change to `core/` or to the shared `schema/*.json` releases every adapter.
  - Mapping drift needs its `revision` bumped and the version added to `observed` (`AGENTS.md`, "Agent drift").
- **Manual check** here means a **consumer check**: a check in the consumer apps or on a real install (`tools/e2e/`), with what to look for.
- **Decisions** live in `AGENTS.md`, `docs/contract.md` and the plan in `tasks/todo.md`.
- If the working tree has uncommitted changes that don't belong to the ticket, stop and ask.

## Branch

`<type>/$1-<short-name>`, with `<type>` one of `feat`, `fix`, `docs`, `chore`.

## Models

- Sonnet:
  - docs that only restate a decided change
  - tests for already specified behavior
  - curating a capture into `fixtures/` by an exact recipe
  - entering texts
- Opus `medium`: ordinary logic outside the core paths.
- Opus `high` (core paths):
  - `core/spool.sh` (POSIX portability, never steer, speed)
  - the contract and the schemas
  - mapping documents and golden files
  - correlation rules
  - capture drivers
  - the release and dist workflow
  - anything that touches how a consumer app sees the data

## Commit and PR

**No commit, no push, no PR.** In `we-are-the-borg` repos the maintainer commits, pushes and opens the PR. Never run `git commit`, `git push`, `gh pr create` or `gh pr merge`.

Once the reviewer says `ship`, propose the following, ready to paste, then stop:

- **PR title:** Conventional Commits (`feat: …`, `fix: …`, `docs: …`, `chore: …`; `feat(contract): …` for changes the apps must know about; `!` for breaking). It becomes the squash commit and drives release-please. Say which adapters it releases and how. Versions and `CHANGELOG.md` are never bumped by hand.
- **PR body:**
  - what changed and why, and the contract impact
  - a test plan: what was verified and what was not, including the consumer check
  - `Closes #$1`, or `Refs #$1` if parts of the issue stay open (e.g. captures the maintainer still has to make)

If the ticket is part of a plan in `tasks/todo.md`, have an implementer tick it there.

## Report

The proposal from `## Commit and PR` instead of commit SHAs and a PR link, plus the consumer check the maintainer still has to do.

## Implementer

**Never run `git commit`, `git push` or `gh pr create`.** In this repo the maintainer commits, not the orchestrator.

**Testing:**

- The hook (`core/spool.sh`): `tests/spool.test.sh`, POSIX `sh`. Run it under `sh` and with `SPOOL_SH=dash`. The tests run the shipped copy in `adapters/claude-code/scripts/`, so run `sh tools/sync.sh` first.
- Mapping documents (`model/`): golden files in `fixtures/<source>/<version>/<run>/expected/`, checked by `python3 tests/model.test.py`.
- Codex adapter and capture tooling: `tests/codex-adapter.test.py`, `tests/codex-capture.test.py`.

Behavior about payloads is backed by **real captures** in `fixtures/`, never by guessed formats. You may capture Claude Code with `tools/hook-capture/claude-code/drive-session-runs.py` (haiku, a few cents), and add a run there if the assignment says so. The maintainer makes Codex captures; if one you need is missing, stop and report it under `DEVIATIONS`.

**Verification chain:** the commands under **Verification** in `AGENTS.md`. Run what applies to the touched parts, and the full test list once at the end.

**`MANUAL_CHECK`** here means what the maintainer should verify in the consumer apps (The Collective, Unimatrix Zero) or on a real install (`tools/e2e/`).

**Project rules** (all in `AGENTS.md`; these are the easiest to break):

- **Never steer.** The hook exits 0 and writes nothing to stdout or stderr, on every path. No hook returns decision fields or context.
- **POSIX `sh`, no runtime dependencies** in the hook: no `node`, `jq`, `python`, no bashisms. It must stay fast enough to run synchronously (the speed test in `tests/spool.test.sh`).
- **Payload byte for byte.** The hook never parses or rewrites the payload; interpretation belongs in the apps, through the mapping documents.
- **Agent-neutral core.** `core/spool.sh` knows no agent; agent specifics live in the adapter and in the contract's per-source sections.
- **Never edit the copies** `adapters/*/scripts/spool.sh`, `adapters/*/schema/`, `adapters/*/model/`. Change `core/`, `schema/` or `model/` and run `sh tools/sync.sh`.
- **Never touch** the dist repos `we-are-the-borg/subspace-<source>`, the versions in plugin manifests, `CHANGELOG.md` or `.release-please-manifest.json`. release-please writes them.
- **Contract:** a change to the envelope, layout or semantics goes into `docs/contract.md` (and the schema) in the same task as the code, as the assignment specifies. Don't decide contract questions yourself; report them under `DEVIATIONS`.
- **Mapping drift:** change only `model/<source>.json`, never drop a path that older captures need, bump its `revision`, and add the version to `observed`.
- **No personal data** in the repository: anonymize captures as `fixtures/README.md` describes, and run `python3 tests/fixtures-privacy.test.py`. No home paths, account identifiers, full transcripts or content of files from the user's machine.
- **English** everywhere.
- **Binding decisions:** `AGENTS.md`, the contract and the plan in `tasks/todo.md`.

## Reviewer

Commands you run may only write to temporary folders (`mktemp -d`) and to the adapter copies that `sh tools/sync.sh` rewrites. If the sync changes any copy, the copies were stale, and that itself is a finding.

**Verification chain:** every line under **Verification** in `AGENTS.md` that applies to the touched parts. For a change to the hook, also run it under `dash`, and feed it a real fixture to see the file it writes.

**Tests** must be backed by real captures in `fixtures/`, not by hand-made JSON alone.

**Project rules to check:**

- the hook never steers: exit 0 and no output on every path, including errors; `async` hooks stay `async`
- the hook is POSIX `sh` with standard utilities only: no `jq`, `node`, `python`, no bashisms, no locale-dependent ranges; the speed test still passes
- the payload stays byte for byte; the hook does not parse it
- `core/spool.sh` stays agent-neutral; agent specifics only in the adapter and in the contract's per-source sections
- the adapter copies match their sources (the sync line under **Verification** in `AGENTS.md` shows no difference)
- contract, schema and hook agree; an envelope or layout change follows contract §9 (`v`); new semantics have a contract note for the apps
- a changed `model/<source>.json` has its `revision` bumped and the captured version in `observed`; no path that older captures need was dropped
- assumptions about payloads come from captures in `fixtures/`, not from guesses or docs alone
- no personal data: home paths, account identifiers, e-mail addresses, full transcripts, user file content (`python3 tests/fixtures-privacy.test.py`, and read new fixtures yourself)
- no hand-edited versions, `CHANGELOG.md` or `.release-please-manifest.json`; nothing written to dist repos
- nothing writes outside `$ROOT`, into repos or into an agent's configuration
- English everywhere
- no contradiction of `AGENTS.md`, the contract or the plan in `tasks/todo.md`
