# Contributing

Thanks for helping. subspace is small on purpose: hooks that only observe, a POSIX `sh` script and a contract for the apps that read its files.

- **Read [`AGENTS.md`](AGENTS.md) first.** It holds the rules for humans and coding agents alike: never steer an agent, no runtime dependencies in the hook, payloads byte for byte, where things live and how releases work.
- **The interface is [`docs/contract.md`](docs/contract.md).** Changes to it affect the apps that read subspace's files; open an issue first.
- **Pull requests** go against `main` and are squash-merged. The PR title becomes the commit message and drives the release, so it follows [Conventional Commits](https://www.conventionalcommits.org/): `feat: …`, `fix: …`, `docs: …`, `chore: …`; `feat(contract): …` for changes the apps must know about; `!` for breaking changes. Never bump versions by hand; release-please does.
- **Don't edit the copies** in `adapters/*/scripts/`, `adapters/*/schema/` and `adapters/*/model/`. Change `core/`, `schema/` or `model/` and run `sh tools/sync.sh`.
- **Tests:** `sh tests/spool.test.sh`, `python3 tests/model.test.py`, `python3 tests/codex-adapter.test.py`, `python3 tests/codex-capture.test.py`, `python3 tests/fixtures-privacy.test.py`. CI runs them on Linux and macOS.
- **Fixtures come from real captures only**, and they are public: anonymize them as [`fixtures/README.md`](fixtures/README.md) describes before you add them. Never commit full transcripts, home paths, account identifiers or the content of your own files.

Security problems: see [`SECURITY.md`](SECURITY.md).
