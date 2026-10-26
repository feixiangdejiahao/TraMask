cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/completion.py')
s = p.read_text()
old = '''    # The preceding argument is the snapshot ID.
    args = split_arg_string(ctx.command_path) if False else []
    snapshot_ids = [s.id for s in self.list_snapshots()]
    if not snapshot_ids:
        return []
    snapshot_id = snapshot_ids[-1]
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
'''
new = '''    # The preceding positional argument is the snapshot ID.
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
'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/termui/completion.py && echo OK