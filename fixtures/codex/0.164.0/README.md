# Fixtures: Codex CLI 0.164.0

Recorded on macOS 27.0 (arm64) on 2026-10-26 with `tools/hook-capture/codex/` (README section 7): `codex-cli 0.164.0`, its managed app-server daemon 0.164.0, and the ChatGPT desktop app's bundled Codex. No hook payloads: the hook events of these runs went to the installed subspace plugin and are not shipped; the run's timeline names each root session's `session_id` as the hooks reported it.

## Runs

| Run | Scenario |
|---|---|
| `1-writer-locks` | Codex's thread writer lock files across exit, closed terminal, crash, resume, child thread, headless and the ChatGPT app (contract §14) |
