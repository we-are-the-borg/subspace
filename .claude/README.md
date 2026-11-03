# Workflow

Optional maintainer tooling. Contributors don't need it; [`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`AGENTS.md`](../AGENTS.md) are all you need.

The maintainer works tickets with `/grmlin:ticket <issue> [--go]`. It comes from the Claude Code plugin [`grmlin`](https://github.com/grmlin/agent-skills): an orchestrator that plans and delegates, an `implementer` per task and a `change-reviewer`. This repo only keeps its specifics, in the profile [`workflow.md`](workflow.md); where the profile differs from the plugin, the profile wins. The orchestrator never commits or pushes here. It ends with a proposed PR title and body.

```sh
claude plugin marketplace add grmlin/agent-skills
claude plugin install grmlin@grmlin --scope user
```

`.codex/agents/` holds the implementer and reviewer for Codex, which the plugin doesn't cover.
