cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/types.py')
s = p.read_text()
old = '''@dataclass
class Snapshot:
    id: int
    name: Optional[str]
    captured_at: float
    running_tasks: Dict[str, FormattedLiveTaskInfo]
    terminated_tasks: Dict[str, FormattedTerminatedTaskInfo]
    terminated_object_ids: Dict[str, str] = field(default_factory=dict)
    stacks: Dict[str, Sequence[FormattedStackItem]] = field(default_factory=dict)
'''
new = '''@dataclass
class Snapshot:
    id: int
    name: Optional[str]
    captured_at: float
    running_tasks: Dict[str, FormattedLiveTaskInfo]
    terminated_tasks: Dict[str, FormattedTerminatedTaskInfo]
    terminated_object_ids: Dict[str, str] = field(default_factory=dict)
    stacks: Dict[str, Sequence[FormattedStackItem]] = field(default_factory=dict)

    @property
    def running_count(self) -> int:
        return len(self.running_tasks)

    @property
    def terminated_count(self) -> int:
        return len(self.terminated_tasks)
'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
mypy aiomonitor/types.py && python -m pytest tests/test_monitor.py -q 2>&1 | tail -3