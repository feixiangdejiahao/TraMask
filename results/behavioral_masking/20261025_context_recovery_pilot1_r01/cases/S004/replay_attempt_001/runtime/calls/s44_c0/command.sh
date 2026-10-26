cd /app && cat > /tmp/cli_test.py <<'EOF'
import asyncio
import contextlib
import contextvars
import functools
import io
import unittest.mock

import aiomonitor.termui.commands
from aiomonitor import Monitor
from aiomonitor.termui.commands import (
    command_done,
    current_monitor,
    current_stdout,
    monitor_cli,
)

class BufferedOutput:
    def __init__(self):
        self._buffer = io.StringIO()
    def write(self, data):
        self._buffer.write(data)
    def write_raw(self, data):
        self._buffer.write(data)


async def invoke_command(monitor, args):
    dummy_stdout = BufferedOutput()
    current_monitor_token = current_monitor.set(monitor)
    current_stdout_token = current_stdout.set(dummy_stdout._buffer)
    fut = asyncio.run_coroutine_threadsafe(asyncio.Event(), monitor._ui_loop)
    command_done_event = await asyncio.wrap_future(fut)
    command_done_token = command_done.set(command_done_event)
    try:
        with unittest.mock.patch.object(
            aiomonitor.termui.commands,
            "print_formatted_text",
            functools.partial(
                aiomonitor.termui.commands.print_formatted_text, output=dummy_stdout
            ),
        ):
            ctx = contextvars.copy_context()
            ctx.run(
                monitor_cli.main,
                args,
                prog_name="",
                obj=monitor,
                standalone_mode=False,
                max_content_width=80,
            )
            fut = asyncio.run_coroutine_threadsafe(
                command_done_event.wait(), monitor._ui_loop
            )
            await asyncio.wrap_future(fut)
    finally:
        command_done.reset(command_done_token)
        current_stdout.reset(current_stdout_token)
        current_monitor.reset(current_monitor_token)
    return dummy_stdout._buffer.getvalue()


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="sleeper1")
        await asyncio.sleep(0.02)
        r = await invoke_command(mon, ["snapshot", "save", "--name", "first"])
        print("SAVE:", repr(r))
        r = await invoke_command(mon, ["snapshot", "list"])
        print("LIST:", repr(r))
        r = await invoke_command(mon, ["snapshot", "ls"])
        print("LS:", repr(r))
        r = await invoke_command(mon, ["snapshot", "show", "1"])
        print("SHOW:", repr(r))
        r = await invoke_command(mon, ["snapshot", "where", "1", str(id(t))])
        print("WHERE:", repr(r))
        r = await invoke_command(mon, ["snapshot", "diff", "1", "1"])
        print("DIFF:", repr(r))
        r = await invoke_command(mon, ["snapshot", "delete", "1"])
        print("DELETE:", repr(r))
        r = await invoke_command(mon, ["snapshot", "show", "1"])
        print("SHOW MISSING:", repr(r))
        r = await invoke_command(mon, ["snapshot", "where", "1", "123"])
        print("WHERE MISSING:", repr(r))
        t.cancel()
        await asyncio.sleep(0.05)


asyncio.run(main())
EOF
python /tmp/cli_test.py