cd /app && cat > /tmp/snap_test.py <<'EOF'
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
        print("sid1", sid1)
        print("list", mon.list_snapshots())
        print("running count", len(mon.format_snapshot_task_list(sid1)))
        print("running ids", [t.task_id for t in mon.format_snapshot_task_list(sid1)])
        stack = mon.format_snapshot_task_stack(sid1, str(id(t1)))
        print("stack header", stack[0].type, stack[0].content[:60])

        await asyncio.sleep(0.1)
        t3 = loop.create_task(sleeper(), name="sleeper3")
        sid2 = await mon.capture_snapshot(name="second")
        print("sid2", sid2, mon.list_snapshots())
        print("diff added", [i.task_id for i in mon.format_snapshot_diff(sid1, sid2).added])
        print("diff removed", [i.task_id for i in mon.format_snapshot_diff(sid1, sid2).removed])
        print("diff common", [i.task_id for i in mon.format_snapshot_diff(sid1, sid2).common])

        # missing lookups
        try:
            mon.get_snapshot(999)
        except KeyError as e:
            print("KeyError snapshot ok", e)
        try:
            mon.format_snapshot_task_stack(sid1, 12345)
        except KeyError as e:
            print("KeyError task ok", e)

        mon.delete_snapshot(sid1)
        print("after delete", [s.id for s in mon.list_snapshots()])
        t1.cancel()
        t3.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/snap_test.py