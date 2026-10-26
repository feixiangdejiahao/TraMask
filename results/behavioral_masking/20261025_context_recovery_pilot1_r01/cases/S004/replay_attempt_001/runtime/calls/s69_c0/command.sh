cd /app && cat > /tmp/complete_debug6.py <<'EOF'
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
        await mon.capture_snapshot()
        token = current_monitor.set(mon)
        ctx = _resolve_context(monitor_cli, {}, "", ["snapshot", "where"])
        cmd_or_param, inc = _resolve_incomplete(ctx, ["snapshot", "where"], "")
        print("custom shell complete:", cmd_or_param._custom_shell_complete)
        print("shell_complete:", cmd_or_param.shell_complete(ctx, inc))
        print("shell_complete list:", list(cmd_or_param.shell_complete(ctx, inc)))
        # call the custom func directly
        fn = cmd_or_param._custom_shell_complete
        if fn is not None:
            print("direct fn:", list(fn(ctx, cmd_or_param, inc)))
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_debug6.py