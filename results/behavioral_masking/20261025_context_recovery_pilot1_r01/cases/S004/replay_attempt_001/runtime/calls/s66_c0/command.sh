cd /app && cat > /tmp/complete_debug4.py <<'EOF'
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
        token = current_monitor.set(mon)
        # Simulate actual ClickCompleter for "snapshot where 1 " (incomplete="")
        for args, incomplete in ((["snapshot", "where"], ""), (["snapshot", "where", "1"], "")):
            ctx = _resolve_context(monitor_cli, {}, "", args)
            cmd_or_param, inc = _resolve_incomplete(ctx, args, incomplete)
            print(args, "->", type(cmd_or_param).__name__, getattr(cmd_or_param, 'name', None), "inc", repr(inc), "params", ctx.params)
            try:
                print("  completions", list(cmd_or_param.shell_complete(ctx, inc)))
            except Exception as e:
                print("  err", type(e), e)
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_debug4.py