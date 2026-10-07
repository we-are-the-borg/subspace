# Daemon permission and compaction workload

Session `01a0f71a-7656-7c02-8461-8d00e7f552ce`, initial daemon-attached segment. All events were hosted by the same detached app-server process; this PID evidence comes from capture metadata and is not part of the raw fixtures.

Two writes each emit pre, permission, post and stop events. The user saw no dialog: the captured turn context selected `approval_policy: on-request` with `approvals_reviewer: auto_review`, and both writes succeeded. The second permission file arrived before its pre-tool file, so consumers must correlate stable fields rather than file order. `PermissionRequest` omits `tool_use_id` and adds `description` to its tool input.

Manual compaction emits `PreCompact`, `PostCompact`, then `SessionStart` with `source: compact`; the following prompt uses a new turn ID. This run is automatic-review evidence only and says nothing about manual approval or rejection.

Source files are the first 18 raw capture JSON files for this session, from `1790852284-37857-iOJcQ8.json` through `1790852373-39099-fbK4eV.json`, numbered by captured delivery order. The later resume segment is run 8.
