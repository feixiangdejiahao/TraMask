cd /app && python - <<'EOF'
from pathlib import Path
p = Path('tests/test_monitor.py')
s = p.read_text()
old = '''@pytest.mark.asyncio
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
'''
new = '''@pytest.mark.asyncio
async def test_snapshot_diff() -> None:
    loop = asyncio.get_running_loop()

    async def sleeper() -> None:
        await asyncio.sleep(100)

    async def short() -> None:
        await asyncio.sleep(0.05)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t1 = loop.create_task(sleeper(), name="snap-a")
        t2 = loop.create_task(short(), name="snap-b")
        await asyncio.sleep(0.01)
        snapshot_id_1 = await mon.capture_snapshot()
        await asyncio.sleep(0.1)
        t3 = loop.create_task(sleeper(), name="snap-c")
        snapshot_id_2 = await mon.capture_snapshot()

        diff = mon.format_snapshot_diff(snapshot_id_1, snapshot_id_2)
        added_ids = {item.task_id for item in diff.added}
        assert str(id(t3)) in added_ids
        common_ids = {item.task_id for item in diff.common}
        assert str(id(t1)) in common_ids
        # t2 completed in between; its object ID remains the same so it is common.
        assert str(id(t2)) in common_ids
        t1.cancel()
        t3.cancel()
        await asyncio.sleep(0.05)
'''
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python -m pytest tests/test_monitor.py -x -q 2>&1 | tail -20