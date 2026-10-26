cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/completion.py')
s = p.read_text()
old = """    # The preceding positional argument is the snapshot ID.
    if not ctx.protected_args:
        return []
    try:
        snapshot_id = ctx.protected_args[-1]
    except IndexError:
        return []
    try:
        return [
            task_id
            for task_id in (
                info.task_id
                for info in self.format_snapshot_task_list(snapshot_id)
            )
            if task_id.startswith(incomplete)
        ][:10]
    except KeyError:
        return []
"""
new = """    # The preceding positional argument is the snapshot ID.
    snapshot_id = ctx.params.get("snapshot_id")
    if snapshot_id is None and ctx.protected_args:
        snapshot_id = ctx.protected_args[-1]
    if snapshot_id is None:
        return []
    try:
        return [
            task_id
            for task_id in (
                info.task_id
                for info in self.format_snapshot_task_list(snapshot_id)
            )
            if task_id.startswith(incomplete)
        ][:10]
    except KeyError:
        return []
"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python /tmp/complete_debug5.py