cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/monitor.py')
s = p.read_text()

old = """        hook_task_factory: bool = False,
        max_termination_history: int = 1000,
        locals: Optional[Dict[str, Any]] = None,
    ) -> None:"""
new = """        hook_task_factory: bool = False,
        max_termination_history: int = 1000,
        max_snapshots: int = 10,
        locals: Optional[Dict[str, Any]] = None,
    ) -> None:"""
assert old in s
s = s.replace(old, new)

old = """        self._terminated_history = []
        self._max_termination_history = max_termination_history
"""
new = """        self._terminated_history = []
        self._max_termination_history = max_termination_history
        self._snapshots = {}
        self._next_snapshot_id = 1
        self._max_snapshots = max_snapshots
"""
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF