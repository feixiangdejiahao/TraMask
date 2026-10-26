cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/monitor.py')
s = p.read_text()

old = """    hook_task_factory: bool = False,
    max_termination_history: Optional[int] = None,
    locals: Optional[Dict[str, Any]] = None,
) -> Monitor:"""
new = """    hook_task_factory: bool = False,
    max_termination_history: Optional[int] = None,
    max_snapshots: Optional[int] = None,
    locals: Optional[Dict[str, Any]] = None,
) -> Monitor:"""
assert old in s
s = s.replace(old, new)

old = """        max_termination_history=(
            max_termination_history
            if max_termination_history is not None
            else get_default_args(monitor_cls.__init__)["max_termination_history"]
        ),
        locals=locals,
    )"""
new = """        max_termination_history=(
            max_termination_history
            if max_termination_history is not None
            else get_default_args(monitor_cls.__init__)["max_termination_history"]
        ),
        max_snapshots=(
            max_snapshots
            if max_snapshots is not None
            else get_default_args(monitor_cls.__init__)["max_snapshots"]
        ),
        locals=locals,
    )"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF