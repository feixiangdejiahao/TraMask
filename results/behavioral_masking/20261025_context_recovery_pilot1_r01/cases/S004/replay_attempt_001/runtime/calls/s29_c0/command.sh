cat > aiomonitor/types.py <<'EOF'
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Union

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from backports.strenum import StrEnum


@dataclass
class FormattedLiveTaskInfo:
    task_id: str
    state: str
    name: str
    coro: str
    created_location: str
    since: str


@dataclass
class FormattedTerminatedTaskInfo:
    task_id: str
    name: str
    coro: str
    started_since: str
    terminated_since: str


class FormatItemTypes(StrEnum):
    HEADER = "header"
    CONTENT = "content"


class FormattedStackItem(NamedTuple):
    type: FormatItemTypes
    content: str


@dataclass
class TerminatedTaskInfo:
    id: str
    name: str
    coro: str
    started_at: float
    terminated_at: float
    cancelled: bool
    termination_stack: Optional[List[traceback.FrameSummary]] = None
    canceller_stack: Optional[List[traceback.FrameSummary]] = None
    exc_repr: Optional[str] = None
    persistent: bool = False
    object_id: Optional[str] = None


@dataclass
class CancellationChain:
    target_id: str
    canceller_id: str
    canceller_stack: Optional[List[traceback.FrameSummary]] = None


SnapshotTaskInfo = Union[FormattedLiveTaskInfo, FormattedTerminatedTaskInfo]


@dataclass
class Snapshot:
    id: int
    name: Optional[str]
    captured_at: float
    running_tasks: Dict[str, FormattedLiveTaskInfo]
    terminated_tasks: Dict[str, FormattedTerminatedTaskInfo]
    terminated_object_ids: Dict[str, str] = field(default_factory=dict)
    stacks: Dict[str, List[FormattedStackItem]] = field(default_factory=dict)


@dataclass
class SnapshotSummary:
    id: int
    name: Optional[str]
    running_count: int
    terminated_count: int


@dataclass
class SnapshotTaskItem:
    task_id: str
    kind: str
    info: SnapshotTaskInfo


@dataclass
class SnapshotDiff:
    added: List[SnapshotTaskItem]
    removed: List[SnapshotTaskItem]
    common: List[SnapshotTaskItem]
EOF
python -c "import aiomonitor.types as t; print(t.Snapshot.__dataclass_fields__.keys())"