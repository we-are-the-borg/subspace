# Headless parallel and reused child workload

Session `01a0f6f3-e902-7f10-9fdd-9a6e4d38a220`, captured with `codex exec` without the daemon. The root ran `pwd`, a failing `sh -c "exit 7"`, and collaboration tools. Alpha and beta overlapped; alpha was reused for a second turn.

Alpha has one start and two stops with distinct turn IDs. Beta's start file arrived after alpha's first stop even though rollout timestamps prove their turns overlapped, so the numbered delivery order must not be used to infer child concurrency. Nested spawning was unavailable to beta and remains unobserved.

All ten tool calls have one pre/post pair by `session_id`, optional `agent_id`, and `tool_use_id`. The failed shell command still has `PostToolUse` with an empty `tool_response`; the hook payload does not contain its exit code. The final stop payload was complete although capture process metadata did not finish; process metadata is intentionally excluded here.

Source files are the 28 raw capture JSON files for this session, from `1790849577-32273-vk19zT.json` through `1790849627-33729-kO40WW.json`, numbered by captured delivery order.

## Edited rollout metadata excerpt

[rollouts/session_meta.jsonl](rollouts/session_meta.jsonl) contains the first `session_meta` line of each collected rollout, root first, then `/root/alpha` and `/root/beta`. This is an **edited excerpt**; full rollouts are not shipped. To remove account identifiers and omit runtime instructions, only these fields were edited in each line:

- `payload.creator_user_id` → `"user-REDACTED"`
- `payload.creator_account_id` → `"00000000-0000-0000-0000-000000000000"`
- `payload.base_instructions.text` → `"<omitted>"`

All remaining bytes are unchanged, including paths, timestamps and git metadata. Each child's `session_id` and `parent_thread_id` match the root's `id`; its `id` matches the hook payloads' `agent_id`. `source.subagent.thread_spawn.agent_path` matches the `/root/alpha` or `/root/beta` task path in the root's `collaborationspawn_agent` post response (events 008 and 013). This links parallel children without relying on event arrival order. The excerpt does not contain turn messages, tool results or exit statuses.
