cd /app && python - <<'EOF'
from pathlib import Path

# types.py
p = Path('aiomonitor/types.py')
s = p.read_text()
old = "    stacks: Dict[str, List[FormattedStackItem]] = field(default_factory=dict)"
new = "    stacks: Dict[str, Sequence[FormattedStackItem]] = field(default_factory=dict)"
assert old in s
s = s.replace(old, new)
s = s.replace("from typing import Dict, List, NamedTuple, Optional, Union", "from typing import Dict, List, NamedTuple, Optional, Sequence, Union")
p.write_text(s)

# monitor.py
p = Path('aiomonitor/monitor.py')
s = p.read_text()
old = """        running_tasks: Dict[str, FormattedLiveTaskInfo] = {}
        stacks: Dict[str, List[FormattedStackItem]] = {}
        current_task = asyncio.current_task()
        capture_code = inspect.currentframe().f_code
"""
new = """        running_tasks: Dict[str, FormattedLiveTaskInfo] = {}
        stacks: Dict[str, Sequence[FormattedStackItem]] = {}
        current_task = asyncio.current_task()
        current_frame = inspect.currentframe()
        assert current_frame is not None
        capture_code = current_frame.f_code
"""
assert old in s
s = s.replace(old, new)

old = """        for info in self.format_running_task_list("", False):
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
new = """        for running_info in self.format_running_task_list("", False):
            if current_task is not None and running_info.task_id == str(id(current_task)):
                if is_capture_task(current_task):
                    # Do not include the transient snapshot-capturing task itself.
                    continue
            running_tasks[running_info.task_id] = running_info
            try:
                stacks[running_info.task_id] = self.format_running_task_stack(
                    running_info.task_id
                )
            except MissingTask:
                # The task may have finished between the two calls.
                continue
"""
assert old in s
s = s.replace(old, new)

old = """        for info in self.format_terminated_task_list("", False):
            terminated_tasks[info.task_id] = info
            tinfo = self._terminated_tasks.get(info.task_id)
            if tinfo is not None and tinfo.object_id is not None:
                terminated_object_ids[info.task_id] = tinfo.object_id
"""
new = """        for terminated_info in self.format_terminated_task_list("", False):
            terminated_tasks[terminated_info.task_id] = terminated_info
            tinfo = self._terminated_tasks.get(terminated_info.task_id)
            if tinfo is not None and tinfo.object_id is not None:
                terminated_object_ids[terminated_info.task_id] = tinfo.object_id
"""
assert old in s
s = s.replace(old, new)

old = """            for task_id, info in snapshot.running_tasks.items():
                items[task_id] = SnapshotTaskItem(task_id, "running", info)
            for trace_id, info in snapshot.terminated_tasks.items():
                object_id = snapshot.terminated_object_ids.get(trace_id, trace_id)
                items[object_id] = SnapshotTaskItem(object_id, "terminated", info)
"""
new = """            for task_id, running_info in snapshot.running_tasks.items():
                items[task_id] = SnapshotTaskItem(task_id, "running", running_info)
            for trace_id, terminated_info in snapshot.terminated_tasks.items():
                object_id = snapshot.terminated_object_ids.get(trace_id, trace_id)
                items[object_id] = SnapshotTaskItem(
                    object_id,
                    "terminated",
                    terminated_info,
                )
"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/types.py aiomonitor/monitor.py && echo OK