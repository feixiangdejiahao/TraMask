cd /app && cat >> tests/test_monitor.py <<'EOF'


@pytest.mark.asyncio
async def test_start_monitor_max_snapshots() -> None:
    loop = asyncio.get_running_loop()
    mon = start_monitor(
        loop,
        console_enabled=False,
        hook_task_factory=True,
        max_snapshots=3,
    )
    try:
        assert mon._max_snapshots == 3
        await mon.capture_snapshot(name="keep")
        await mon.capture_snapshot()
        await mon.capture_snapshot()
        await mon.capture_snapshot()
        ids = [s.id for s in mon.list_snapshots()]
        assert ids == [1, 3, 4]
    finally:
        mon.close()
EOF
python -m pytest tests/test_monitor.py -q -p no:warnings 2>&1 | tail -4