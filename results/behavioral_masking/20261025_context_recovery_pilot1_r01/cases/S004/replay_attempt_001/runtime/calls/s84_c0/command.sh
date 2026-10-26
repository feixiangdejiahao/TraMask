cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/types.py')
s = p.read_text()
old = '''@dataclass
class SnapshotTaskItem:
    task_id: str
    kind: str
    info: SnapshotTaskInfo
'''
new = '''@dataclass
class SnapshotTaskItem:
    task_id: str
    kind: str
    info: SnapshotTaskInfo

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def coro(self) -> str:
        return self.info.coro

    @property
    def state(self) -> Optional[str]:
        return getattr(self.info, "state", None)

    @property
    def created_location(self) -> Optional[str]:
        return getattr(self.info, "created_location", None)

    @property
    def since(self) -> Optional[str]:
        return getattr(self.info, "since", None)

    @property
    def started_since(self) -> Optional[str]:
        return getattr(self.info, "started_since", None)

    @property
    def terminated_since(self) -> Optional[str]:
        return getattr(self.info, "terminated_since", None)
'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/types.py && mypy aiomonitor/types.py && echo OK