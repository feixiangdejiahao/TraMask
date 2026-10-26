cd /app && cat > /tmp/diff_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    async def short():
        await asyncio.sleep(0.05)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t1 = loop.create_task(sleeper(), name="sleeper1")
        t2 = loop.create_task(short(), name="short1")
        await asyncio.sleep(0.01)
        sid1 = await mon.capture_snapshot()
        await asyncio.sleep(0.1)
        sid2 = await mon.capture_snapshot()
        diff = mon.format_snapshot_diff(sid1, sid2)
        print("added:", [(i.task_id, i.kind, i.info.name) for i in diff.added])
        print("removed:", [(i.task_id, i.kind, i.info.name) for i in diff.removed])
        print("common:", [(i.task_id, i.kind, i.info.name) for i in diff.common])
        t1.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/diff_test.py