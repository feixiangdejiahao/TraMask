cd /app && cat > /tmp/group_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor
from tests.test_monitor import invoke_command


async def main():
    loop = asyncio.get_running_loop()
    with Monitor(loop, console_enabled=False) as mon:
        try:
            r = await invoke_command(mon, ["snapshot"])
            print("OK:", repr(r))
        except Exception as e:
            print("EXC:", type(e), e)


asyncio.run(main())
EOF
cd /app && python -c "import sys; sys.path.insert(0,'tests'); import test_monitor" 2>/dev/null; python /tmp/group_test.py