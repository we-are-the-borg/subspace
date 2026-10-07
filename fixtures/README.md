# Fixtures

Real hook payloads per agent and version, curated from captures (`tools/hook-capture/<source>/`). Each `<source>/<version>/README.md` describes its runs; [`docs/model.md` §7](../docs/model.md#7-golden-files) describes the golden files.

## Anonymization

Payloads, status files and rollout excerpts are kept byte for byte, with these replacements applied consistently across `events/`, `expected/`, `status/` and `status-expected/`:

- Home directory → `/Users/user/` (also in Claude Code's encoded project names, `-Users-user-…`).
- Capture repository → `/Users/user/dev/subspace/`; its git remote → `git@github.com:example/subspace.git`, commit hashes → forty zeros.
- Opaque values nobody can inspect, such as Codex's encrypted spawn `message` → `<encrypted message omitted>`.
- Account identifiers and e-mail addresses → zero UUIDs, `user-REDACTED`, `user@example.com`.
- Files a run read from the user's machine (not the capture's own files): content → a short placeholder with line counts adjusted, path → a neutral one.
- Full transcripts are not included: they carry the agent's system prompt, the user's instruction files and account data.

`tests/fixtures-privacy.test.py` (CI) fails on home paths other than `/Users/user/`, per-user temp folders, e-mail addresses other than placeholders, unredacted account identifiers, credentials and instruction-file dumps. Anonymize a new capture before adding it, then run that test.
