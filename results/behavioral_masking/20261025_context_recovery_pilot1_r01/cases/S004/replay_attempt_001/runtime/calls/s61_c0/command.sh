cd /app && cat > /tmp/complete_debug.py <<'EOF'
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
        print("snapshots", [(s.id, s.running_count) for s in mon.list_snapshots()])
        token = current_monitor.set(mon)
        args = ["snapshot", "where", str(sid), ""]
        ctx = _resolve_context(monitor_cli, {}, "", args)
        print("ctx.protected_args:", ctx.protected_args)
        print("ctx.args:", ctx.args)
        cmd_or_param, incomplete = _resolve_incomplete(ctx, args, "")
        print("cmd_or_param:", cmd_or_param, type(cmd_or_param))
        print("incomplete:", repr(incomplete))
        # try calling completion with the resolved context
        if hasattr(cmd_or_param, 'shell_complete'):
            print("shell_complete:", list(cmd_or_param.shell_complete(ctx, incomplete)))
        # direct complete_snapshot_task_id
        from aiomonitor.termui.completion import complete_snapshot_task_id
        print("direct:", list(complete_snapshot_task_id(ctx, None, "")))
        current_monitor.reset(token)
        t.cancel()
        await asyncio.sleep(0.1)


asyncio.run(main())
EOF
python /tmp/complete_debug.py