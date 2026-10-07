# Manual permission, remembered approval and rejection

Session `01a0f729-bad4-7a40-8595-d83cd9b7d8f0`, embedded without the daemon and with the manual reviewer selected.

The first write was approved. A later identical write was approved with its command prefix saved; the next repetition emits pre, post and stop without `PermissionRequest`, establishing remembered approval for this captured command.

For the rejected turn, the user confirmed selecting **“Reject and tell Codex what to do instead”** (or similarly worded) in the permission dialog. The permission event arrived just before the pre-tool event, followed by interrupt, with no post or stop. The rollout recorded `aborted by user` and the probe file was absent. This does not establish how other rejection actions are represented.

Each requesting turn contains one shell call, making correlation by session, turn, tool name and command unambiguous even though permission events lack `tool_use_id`. Concurrent identical requests remain untested.

Source files are the 19 raw capture JSON files for this session, from `1790853104-42227-AboDsm.json` through `1790853199-43349-n0iNP4.json`, numbered by captured delivery order.
