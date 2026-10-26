cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/monitor.py')
s = p.read_text()

# Update types import
old = """from .types import (
    CancellationChain,
    FormatItemTypes,
    FormattedLiveTaskInfo,
    FormattedStackItem,
    FormattedTerminatedTaskInfo,
    TerminatedTaskInfo,
)"""
new = """from .types import (
    CancellationChain,
    FormatItemTypes,
    FormattedLiveTaskInfo,
    FormattedStackItem,
    FormattedTerminatedTaskInfo,
    Snapshot,
    SnapshotDiff,
    SnapshotSummary,
    SnapshotTaskItem,
    TerminatedTaskInfo,
)"""
assert old in s
s = s.replace(old, new)

# Add class annotations
old = """    _canceller_chain: Dict[str, str]
    _canceller_stacks: Dict[str, List[traceback.FrameSummary] | None]
    _cancellation_chain_queue: janus.Queue[CancellationChain]
"""
new = """    _canceller_chain: Dict[str, str]
    _canceller_stacks: Dict[str, List[traceback.FrameSummary] | None]
    _cancellation_chain_queue: janus.Queue[CancellationChain]
    _snapshots: Dict[int, Snapshot]
"""
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF