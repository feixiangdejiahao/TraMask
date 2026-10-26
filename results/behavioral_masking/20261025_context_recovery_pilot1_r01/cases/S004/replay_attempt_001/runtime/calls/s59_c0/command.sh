cd /app && cat > /tmp/nohook_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=False) as mon:
        t = loop.create_task(sleeper(), name="sleeper1")
        await asyncio.sleep(0.01)
        sid = await mon.capture_snapshot()
        tasks = mon.format_snapshot_task_list(sid)
        for task in tasks:
            print(task.name, repr(task.since), repr(task.created_location))
        stack = mon.format_snapshot_task_stack(sid, str(id(t)))
        print("stack content:", [s.content[:50] for s in stack])
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/nohook_test.py