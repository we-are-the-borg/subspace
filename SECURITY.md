# Security

subspace runs as a hook inside coding agents and writes what they pass to it into a local folder. Please report anything that could let it leak that data, write outside its plugin data folder, run code it shouldn't, or steer an agent.

## Reporting a vulnerability

Report privately through [GitHub's private vulnerability reporting](https://github.com/we-are-the-borg/subspace/security/advisories/new). Please don't open a public issue for security problems.

Include the agent and its version, the subspace version (`plugin.json` in the plugin data folder), your OS, and steps to reproduce. You'll get an answer as soon as possible; this is a spare-time project, so please allow a few days.

## Supported versions

Only the latest release of each adapter (`claude-code-*`, `codex-*`) gets fixes.
