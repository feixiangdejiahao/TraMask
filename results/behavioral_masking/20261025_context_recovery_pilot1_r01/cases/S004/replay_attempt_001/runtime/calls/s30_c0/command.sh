cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/task.py')
s = p.read_text()
old = """        task_info = TerminatedTaskInfo(
            self_id,
            name=self.get_name(),
            coro=_format_coroutine(self._orig_coro).partition(" ")[0],
            started_at=self._started_at,
            terminated_at=time.perf_counter(),
            cancelled=self.cancelled(),
            termination_stack=self._termination_stack,
            canceller_stack=None,
            exc_repr=exc_repr,
            persistent=self._persistent,
        )"""
new = """        task_info = TerminatedTaskInfo(
            self_id,
            name=self.get_name(),
            coro=_format_coroutine(self._orig_coro).partition(" ")[0],
            started_at=self._started_at,
            terminated_at=time.perf_counter(),
            cancelled=self.cancelled(),
            termination_stack=self._termination_stack,
            canceller_stack=None,
            exc_repr=exc_repr,
            persistent=self._persistent,
            object_id=str(id(self)),
        )"""
assert old in s
p.write_text(s.replace(old, new))
print("done")
EOF