cd /app && cat > /tmp/id_test.py <<'EOF'
import asyncio
from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()
    with Monitor(loop, console_enabled=False) as mon:
        s1 = await mon.capture_snapshot()
        mon.delete_snapshot(s1)
        s2 = await mon.capture_snapshot()
        print("s1", s1, "s2", s2)


asyncio.run(main())
EOF
python /tmp/id_test.py