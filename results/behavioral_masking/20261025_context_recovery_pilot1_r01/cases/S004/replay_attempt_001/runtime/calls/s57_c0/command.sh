cd /app && cat > /tmp/evict_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()
    with Monitor(loop, console_enabled=False, max_snapshots=2) as mon:
        await mon.capture_snapshot()
        await mon.capture_snapshot(name="keep")
        await mon.capture_snapshot()
        print("after 3:", [(s.id, s.name) for s in mon.list_snapshots()])
        await mon.capture_snapshot(name="keep2")
        print("after 4:", [(s.id, s.name) for s in mon.list_snapshots()])
        await mon.capture_snapshot(name="keep3")
        print("after 5:", [(s.id, s.name) for s in mon.list_snapshots()])


asyncio.run(main())
EOF
python /tmp/evict_test.py