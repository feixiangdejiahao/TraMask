cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/completion.py')
s = p.read_text()

old = '''def complete_signal_names(
    ctx: click.Context,
    param: click.Parameter,
    incomplete: str,
) -> Iterable[str]:
    return [sig.name for sig in signal.Signals if sig.name.startswith(incomplete)]
'''
new = '''def complete_signal_names(
    ctx: click.Context,
    param: click.Parameter,
    incomplete: str,
) -> Iterable[str]:
    return [sig.name for sig in signal.Signals if sig.name.startswith(incomplete)]


def complete_snapshot_id(
    ctx: click.Context,
    param: click.Parameter,
    incomplete: str,
) -> Iterable[str]:
    try:
        self: Monitor = current_monitor.get()
    except LookupError:
        return []
    return [
        str(snapshot.id)
        for snapshot in self.list_snapshots()
        if str(snapshot.id).startswith(incomplete)
    ][:10]


def complete_snapshot_task_id(
    ctx: click.Context,
    param: click.Parameter,
    incomplete: str,
) -> Iterable[str]:
    try:
        self: Monitor = current_monitor.get()
    except LookupError:
        return []
    # The preceding argument is the snapshot ID.
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
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/termui/completion.py && echo OK