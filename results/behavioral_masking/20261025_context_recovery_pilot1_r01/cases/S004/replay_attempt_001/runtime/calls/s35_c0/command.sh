cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/monitor.py')
s = p.read_text()

anchor = """        return formatted_stack_list

    async def _coro_wrapper(self, coro: Awaitable[T_co]) -> T_co:
"""
insert = '''        return formatted_stack_list

    def _get_snapshot(self, snapshot_id: str | int) -> Snapshot:
        try:
            snapshot_id_int = int(snapshot_id)
        except (TypeError, ValueError):
            raise KeyError(snapshot_id) from None
        try:
            return self._snapshots[snapshot_id_int]
        except KeyError:
            raise KeyError(snapshot_id) from None

    async def capture_snapshot(
        self,
        name: Optional[str] = None,
    ) -> int:
        """
        Capture a snapshot of the current running and terminated task state.

        The returned snapshot ID auto-increments from 1.  Unnamed snapshots are
        evicted first when the number of snapshots exceeds ``max_snapshots``,
        preserving named snapshots as much as possible.
        """
        if asyncio.get_running_loop() is not self._monitored_loop:
            fut = asyncio.run_coroutine_threadsafe(
                self.capture_snapshot(name=name),
                loop=self._monitored_loop,
            )
            return await asyncio.wrap_future(fut)

        running_tasks: Dict[str, FormattedLiveTaskInfo] = {}
        stacks: Dict[str, List[FormattedStackItem]] = {}
        for info in self.format_running_task_list("", False):
            running_tasks[info.task_id] = info
            try:
                stacks[info.task_id] = self.format_running_task_stack(info.task_id)
            except MissingTask:
                # The task may have finished between the two calls.
                continue

        terminated_tasks: Dict[str, FormattedTerminatedTaskInfo] = {}
        terminated_object_ids: Dict[str, str] = {}
        for info in self.format_terminated_task_list("", False):
            terminated_tasks[info.task_id] = info
            tinfo = self._terminated_tasks.get(info.task_id)
            if tinfo is not None and tinfo.object_id is not None:
                terminated_object_ids[info.task_id] = tinfo.object_id

        snapshot_id = self._next_snapshot_id
        self._next_snapshot_id += 1
        self._snapshots[snapshot_id] = Snapshot(
            id=snapshot_id,
            name=name,
            captured_at=time.perf_counter(),
            running_tasks=running_tasks,
            terminated_tasks=terminated_tasks,
            terminated_object_ids=terminated_object_ids,
            stacks=stacks,
        )

        # Evict oldest unnamed snapshots first, preserving named snapshots.
        while len(self._snapshots) > self._max_snapshots:
            unnamed = sorted(
                (s for s in self._snapshots.values() if s.name is None),
                key=lambda s: s.id,
            )
            if unnamed:
                del self._snapshots[unnamed[0].id]
            else:
                oldest = min(self._snapshots.values(), key=lambda s: s.id)
                del self._snapshots[oldest.id]

        return snapshot_id

    def list_snapshots(self) -> Sequence[SnapshotSummary]:
        """
        Return a list of snapshot summaries sorted by snapshot ID.
        """
        return [
            SnapshotSummary(
                id=s.id,
                name=s.name,
                running_count=len(s.running_tasks),
                terminated_count=len(s.terminated_tasks),
            )
            for s in sorted(self._snapshots.values(), key=lambda s: s.id)
        ]

    def get_snapshot(self, snapshot_id: str | int) -> Snapshot:
        """
        Return the snapshot with the given ID.

        Raises :exc:`KeyError` if there is no such snapshot.
        """
        return self._get_snapshot(snapshot_id)

    def delete_snapshot(self, snapshot_id: str | int) -> None:
        """
        Delete the snapshot with the given ID.

        Raises :exc:`KeyError` if there is no such snapshot.
        """
        snapshot = self._get_snapshot(snapshot_id)
        del self._snapshots[snapshot.id]

    def format_snapshot_task_list(
        self,
        snapshot_id: str | int,
    ) -> Sequence[FormattedLiveTaskInfo]:
        """
        Return the running tasks frozen in the given snapshot.
        """
        snapshot = self._get_snapshot(snapshot_id)
        return list(snapshot.running_tasks.values())

    def format_snapshot_terminated_task_list(
        self,
        snapshot_id: str | int,
    ) -> Sequence[FormattedTerminatedTaskInfo]:
        """
        Return the terminated tasks frozen in the given snapshot.
        """
        snapshot = self._get_snapshot(snapshot_id)
        return list(snapshot.terminated_tasks.values())

    def format_snapshot_task_stack(
        self,
        snapshot_id: str | int,
        task_id: str | int,
    ) -> Sequence[FormattedStackItem]:
        """
        Return the stack of a running task frozen in the given snapshot.

        Raises :exc:`KeyError` if the snapshot or the task does not exist.
        """
        snapshot = self._get_snapshot(snapshot_id)
        task_id_str = str(task_id)
        try:
            return snapshot.stacks[task_id_str]
        except KeyError:
            raise KeyError(task_id) from None

    def format_snapshot_diff(
        self,
        snapshot_id_1: str | int,
        snapshot_id_2: str | int,
    ) -> SnapshotDiff:
        """
        Compare two snapshots by task object ID.

        Returns a :class:`SnapshotDiff` with ``added``, ``removed`` and
        ``common`` lists of :class:`SnapshotTaskItem`.
        """
        snapshot_1 = self._get_snapshot(snapshot_id_1)
        snapshot_2 = self._get_snapshot(snapshot_id_2)

        def items_of(
            snapshot: Snapshot,
        ) -> Dict[str, SnapshotTaskItem]:
            items: Dict[str, SnapshotTaskItem] = {}
            for task_id, info in snapshot.running_tasks.items():
                items[task_id] = SnapshotTaskItem(task_id, "running", info)
            for trace_id, info in snapshot.terminated_tasks.items():
                object_id = snapshot.terminated_object_ids.get(trace_id, trace_id)
                items[object_id] = SnapshotTaskItem(object_id, "terminated", info)
            return items

        items_1 = items_of(snapshot_1)
        items_2 = items_of(snapshot_2)
        removed_keys = sorted(set(items_1) - set(items_2))
        added_keys = sorted(set(items_2) - set(items_1))
        common_keys = sorted(set(items_1) & set(items_2))
        return SnapshotDiff(
            added=[items_2[k] for k in added_keys],
            removed=[items_1[k] for k in removed_keys],
            common=[items_2[k] for k in common_keys],
        )

    async def _coro_wrapper(self, coro: Awaitable[T_co]) -> T_co:
'''
assert anchor in s
s = s.replace(anchor, insert)
p.write_text(s)
print("ok")
EOF