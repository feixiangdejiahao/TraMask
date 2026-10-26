cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/monitor.py')
s = p.read_text()

# add import inspect
old = """import functools
import logging
import sys"""
new = """import functools
import inspect
import logging
import sys"""
assert old in s
s = s.replace(old, new)

# Modify capture_snapshot to skip the capture task itself.
old = """        running_tasks: Dict[str, FormattedLiveTaskInfo] = {}
        stacks: Dict[str, List[FormattedStackItem]] = {}
        for info in self.format_running_task_list("", False):
            running_tasks[info.task_id] = info
            try:
                stacks[info.task_id] = self.format_running_task_stack(info.task_id)
            except MissingTask:
                # The task may have finished between the two calls.
                continue
"""
new = """        running_tasks: Dict[str, FormattedLiveTaskInfo] = {}
        stacks: Dict[str, List[FormattedStackItem]] = {}
        current_task = asyncio.current_task()
        capture_code = inspect.currentframe().f_code

        def is_capture_task(task: asyncio.Task[Any]) -> bool:
            coro = getattr(task, "_coro", None)
            if coro is not None and getattr(coro, "cr_code", None) is capture_code:
                return True
            orig_coro = getattr(task, "_orig_coro", None)
            if orig_coro is not None and getattr(orig_coro, "cr_code", None) is capture_code:
                return True
            return False

        for info in self.format_running_task_list("", False):
            if current_task is not None and info.task_id == str(id(current_task)):
                if is_capture_task(current_task):
                    # Do not include the transient snapshot-capturing task itself.
                    continue
            running_tasks[info.task_id] = info
            try:
                stacks[info.task_id] = self.format_running_task_stack(info.task_id)
            except MissingTask:
                # The task may have finished between the two calls.
                continue
"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/monitor.py && echo OK