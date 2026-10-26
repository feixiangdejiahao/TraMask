cd /app && cat > /tmp/complete_test.py <<'EOF'
import asyncio
from click.shell_completion import _resolve_context, _resolve_incomplete, split_arg_string
from aiomonitor import Monitor
from aiomonitor.context import current_monitor
from aiomonitor.termui.completion import ClickCompleter
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
        cmd_or_param, incomplete = _resolve_incomplete(ctx, args, "")
        print("cmd/param:", cmd_or_param, "incomplete:", repr(incomplete))
        print("completions:", list(cmd_or_param.shell_complete(ctx, incomplete)))
        # snapshot id completion
        args2 = ["snapshot", "where", ""]
        ctx2 = _resolve_context(monitor_cli, {}, "", args2)
        cmd_or_param2, incomplete2 = _resolve_incomplete(ctx2, args2, "")
        print("snap completions:", list(cmd_or_param2.shell_complete(ctx2, incomplete2)))
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_test.py