cd /app && cat > /tmp/help_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor
from tests.test_monitor import invoke_command


async def main():
    loop = asyncio.get_running_loop()
    with Monitor(loop, console_enabled=False) as mon:
        for args in (["snapshot", "--help"], ["snapshot", "save", "--help"], ["snapshot", "where", "--help"]):
            try:
                r = await invoke_command(mon, args)
                print(args, "-> OK", repr(r[:80]))
            except Exception as e:
                print(args, "-> EXC", type(e).__name__, e)


asyncio.run(main())
EOF
cd /app && python /tmp/help_test.py