cd /app && git config user.email "aiomonitor@example.com" && git config user.name "aiomonitor contributor" && git commit -m "feat: add task state snapshots to monitor

Add the ability to capture and compare running and terminated task state
over time:

- Monitor.capture_snapshot() freezes running/terminated task state with
  auto-incrementing IDs and optional names
- Monitor/start_monitor accept max_snapshots (default 10), evicting the
  oldest unnamed snapshots first while preserving named ones
- New Monitor APIs: list_snapshots, get_snapshot, delete_snapshot,
  format_snapshot_task_list, format_snapshot_terminated_task_list,
  format_snapshot_task_stack, format_snapshot_diff
- Diff compares snapshots by task object ID and reports added, removed
  and common task items; missing snapshot/task lookups raise KeyError
- New terminal UI 'snapshot' command group (save, list/ls, show, where,
  diff, delete) with completion and error feedback
- New web API endpoints under /api/snapshot/ and a /snapshots page
- Add tests for capture, eviction, diff, CLI, and web API" && git log --oneline -3 && git status