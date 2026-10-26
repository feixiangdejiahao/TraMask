cd /app && cat >> tests/test_monitor.py <<'EOF'


@pytest.mark.asyncio
async def test_snapshot_capture_list_delete(monitor: Monitor) -> None:
    loop = monitor._monitored_loop

    async def sleeper() -> None:
        await asyncio.sleep(100)

    t = loop.create_task(sleeper(), name="snap-sleeper")
    await asyncio.sleep(0.01)
    snapshot_id = await monitor.capture_snapshot(name="first")
    assert snapshot_id == 1

    summaries = monitor.list_snapshots()
    assert len(summaries) == 1
    assert summaries[0].id == 1
    assert summaries[0].name == "first"
    assert summaries[0].running_count >= 1

    tasks = monitor.format_snapshot_task_list(1)
    assert any(task.name == "snap-sleeper" for task in tasks)

    stack = monitor.format_snapshot_task_stack(1, str(id(t)))
    assert len(stack) > 0

    monitor.delete_snapshot(1)
    assert monitor.list_snapshots() == []
    t.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_snapshot_eviction(event_loop) -> None:
    with Monitor(event_loop, console_enabled=False, max_snapshots=2) as mon:
        await mon.capture_snapshot()
        await mon.capture_snapshot(name="keep")
        await mon.capture_snapshot()
        assert [s.id for s in mon.list_snapshots()] == [2, 3]

        await mon.capture_snapshot(name="keep2")
        assert [(s.id, s.name) for s in mon.list_snapshots()] == [
            (2, "keep"),
            (4, "keep2"),
        ]

        await mon.capture_snapshot(name="keep3")
        assert [(s.id, s.name) for s in mon.list_snapshots()] == [
            (4, "keep2"),
            (5, "keep3"),
        ]


@pytest.mark.asyncio
async def test_snapshot_diff(monitor: Monitor) -> None:
    loop = monitor._monitored_loop

    async def sleeper() -> None:
        await asyncio.sleep(100)

    async def short() -> None:
        await asyncio.sleep(0.05)

    t1 = loop.create_task(sleeper(), name="snap-a")
    t2 = loop.create_task(short(), name="snap-b")
    await asyncio.sleep(0.01)
    snapshot_id_1 = await monitor.capture_snapshot()
    await asyncio.sleep(0.1)
    t3 = loop.create_task(sleeper(), name="snap-c")
    snapshot_id_2 = await monitor.capture_snapshot()

    diff = monitor.format_snapshot_diff(snapshot_id_1, snapshot_id_2)
    added_ids = {item.task_id for item in diff.added}
    assert str(id(t3)) in added_ids
    common_ids = {item.task_id for item in diff.common}
    assert str(id(t1)) in common_ids
    # t2 completed in between; its object ID remains the same so it is common.
    assert str(id(t2)) in common_ids
    t1.cancel()
    t3.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_snapshot_missing_raises_keyerror(monitor: Monitor) -> None:
    with pytest.raises(KeyError):
        monitor.get_snapshot(999)
    with pytest.raises(KeyError):
        monitor.format_snapshot_task_list(999)
    with pytest.raises(KeyError):
        monitor.format_snapshot_terminated_task_list(999)
    with pytest.raises(KeyError):
        monitor.format_snapshot_task_stack(999, 1)
    with pytest.raises(KeyError):
        monitor.delete_snapshot(999)

    snapshot_id = await monitor.capture_snapshot()
    with pytest.raises(KeyError):
        monitor.format_snapshot_task_stack(snapshot_id, 12345)
    with pytest.raises(KeyError):
        monitor.format_snapshot_diff(snapshot_id, 999)


@pytest.mark.asyncio
async def test_snapshot_cli(monitor: Monitor) -> None:
    loop = monitor._monitored_loop

    async def sleeper() -> None:
        await asyncio.sleep(100)

    t = loop.create_task(sleeper(), name="snap-sleeper")
    await asyncio.sleep(0.01)

    resp = await invoke_command(monitor, ["snapshot", "save", "--name", "cli-name"])
    assert "1" in resp
    assert "cli-name" in resp

    resp = await invoke_command(monitor, ["snapshot", "list"])
    assert "1" in resp

    resp = await invoke_command(monitor, ["snapshot", "ls"])
    assert "1" in resp

    resp = await invoke_command(monitor, ["snapshot", "show", "1"])
    assert "snap-sleeper" in resp

    resp = await invoke_command(monitor, ["snapshot", "where", "1", str(id(t))])
    assert "Task" in resp

    resp = await invoke_command(monitor, ["snapshot", "diff", "1", "1"])
    assert "Common" in resp

    resp = await invoke_command(monitor, ["snapshot", "delete", "1"])
    assert "Deleted" in resp

    resp = await invoke_command(monitor, ["snapshot", "show", "1"])
    assert "No snapshot" in resp

    resp = await invoke_command(monitor, ["snapshot", "where", "1", "123"])
    assert "No snapshot" in resp

    t.cancel()
    await asyncio.sleep(0.05)
EOF
python -m pytest tests/test_monitor.py -x -q 2>&1 | tail -40