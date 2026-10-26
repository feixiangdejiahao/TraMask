cd /app && cat > /tmp/complete_debug5.py <<'EOF'
import asyncio
from click.shell_completion import _resolve_context, _resolve_incomplete
from aiomonitor import Monitor
from aiomonitor.context import current_monitor
from aiomonitor.termui.commands import monitor_cli
from aiomonitor.termui.completion import complete_snapshot_id, complete_snapshot_task_id


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="sleeper1")
        await asyncio.sleep(0.01)
        sid = await mon.capture_snapshot()
        token = current_monitor.set(mon)
        print("direct snapshot ids", list(complete_snapshot_id(None, None, "")))
        ctx = _resolve_context(monitor_cli, {}, "", ["snapshot", "where"])
        print("snapshot params", ctx.params)
        print("snapshot completion", list(complete_snapshot_id(ctx, None, "")))
        ctx2 = _resolve_context(monitor_cli, {}, "", ["snapshot", "where", "1"])
        print("task params", ctx2.params)
        print("task completion", list(complete_snapshot_task_id(ctx2, None, "")))
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_debug5.py