cd /app && cat > /tmp/webtest2.py <<'EOF'
import asyncio

import aiohttp.test_utils

from aiomonitor import Monitor
from aiomonitor.webui.app import init_webui


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="web-sleeper")
        await asyncio.sleep(0.01)
        app = await init_webui(mon)
        client = aiohttp.test_utils.TestClient(app)
        async with client:
            resp = await client.post("/api/snapshot/", data={"name": "web"})
            print("save", resp.status, await resp.json())
            sid = (await resp.json())["id"]
            resp = await client.get("/api/snapshot/")
            print("list", resp.status, await resp.json())
            resp = await client.post("/api/snapshot/tasks", data={"snapshot_id": sid})
            data = await resp.json()
            print("tasks", resp.status, data)
            task_id = [x["task_id"] for x in data["tasks"] if x["name"] == "web-sleeper"][0]
            resp = await client.post("/api/snapshot/trace", data={"snapshot_id": sid, "task_id": task_id})
            print("trace", resp.status, (await resp.json())["trace"][0]["type"])
            resp = await client.post("/api/snapshot/diff", data={"snapshot_id_1": sid, "snapshot_id_2": sid})
            print("diff", resp.status, list((await resp.json()).keys()))
            resp = await client.delete(f"/api/snapshot?snapshot_id={sid}")
            print("delete", resp.status, await resp.json())
            resp = await client.post("/api/snapshot/tasks", data={"snapshot_id": 999})
            print("missing", resp.status)
            resp = await client.get("/snapshots")
            text = await resp.text()
            print("page", resp.status, "Snapshots" in text)
        t.cancel()
        await asyncio.sleep(0.05)


asyncio.run(main())
EOF
python /tmp/webtest2.py