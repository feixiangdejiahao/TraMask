cd /app && cat > /tmp/complete_debug2.py <<'EOF'
import asyncio
from click.shell_completion import _resolve_context, _resolve_incomplete
from aiomonitor import Monitor
from aiomonitor.context import current_monitor
from aiomonitor.termui.commands import monitor_cli


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="sleeper1")
        await asyncio.sleep(0.01)
        sid = await mon.capture_snapshot()
        token = current_monitor.set(mon)
        args = ["snapshot", "where", str(sid), ""]
        ctx = _resolve_context(monitor_cli, {}, "", args)
        print("command:", ctx.command.name)
        print("_protected_args:", ctx._protected_args)
        print("args:", ctx.args)
        print("params:", ctx.params)
        print("parent protected:", ctx.parent._protected_args if ctx.parent else None)
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_debug2.py