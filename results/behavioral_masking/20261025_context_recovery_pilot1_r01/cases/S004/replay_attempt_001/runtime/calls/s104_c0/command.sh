cd /app && cat > /tmp/term_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()

    async def short():
        await asyncio.sleep(0.05)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(short(), name="short1")
        await t
        await asyncio.sleep(0.1)  # let termination handler process
        sid = await mon.capture_snapshot()
        terms = mon.format_snapshot_terminated_task_list(sid)
        print("terminated count", len(terms))
        for x in terms:
            print(x.task_id, x.name, x.started_since, x.terminated_since)
        print("summary", mon.list_snapshots())


asyncio.run(main())
EOF
python /tmp/term_test.py