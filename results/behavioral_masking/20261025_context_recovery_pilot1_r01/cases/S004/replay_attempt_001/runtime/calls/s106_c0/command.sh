cd /app && cat > /tmp/start_test.py <<'EOF'
import asyncio
from aiomonitor import start_monitor, Monitor


async def main():
    loop = asyncio.get_running_loop()
    m = start_monitor(loop, console_enabled=False, max_snapshots=3, hook_task_factory=True)
    try:
        await m.capture_snapshot(name="x")
        await m.capture_snapshot()
        await m.capture_snapshot()
        await m.capture_snapshot()
        print([(s.id, s.name) for s in m.list_snapshots()])
        assert m._max_snapshots == 3
    finally:
        m.close()


asyncio.run(main())
EOF
python /tmp/start_test.py