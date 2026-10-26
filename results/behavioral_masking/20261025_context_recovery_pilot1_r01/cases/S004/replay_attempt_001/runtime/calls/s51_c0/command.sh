cd /app && cat > /tmp/web_test.py <<'EOF'
import asyncio
import json

import aiohttp

from aiomonitor import Monitor


async def main():
    loop = asyncio.get_running_loop()

    async def sleeper():
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="sleeper1")
        await asyncio.sleep(0.05)
        base = "http://127.0.0.1:20102"
        async with aiohttp.ClientSession() as session:
            # save
            async with session.post(base + "/api/snapshot/", data={"name": "web1"}) as resp:
                print("save status", resp.status)
                data = await resp.json()
                print("save", data)
                sid = data["id"]
            # list
            async with session.get(base + "/api/snapshot/") as resp:
                print("list status", resp.status)
                print("list", await resp.json())
            # tasks
            async with session.post(base + "/api/snapshot/tasks", data={"snapshot_id": sid}) as resp:
                print("tasks status", resp.status)
                d = await resp.json()
                print("tasks count", len(d["tasks"]), [x["name"] for x in d["tasks"]])
            # trace
            task_id = [x["task_id"] for x in d["tasks"] if x["name"] == "sleeper1"][0]
            async with session.post(base + "/api/snapshot/trace", data={"snapshot_id": sid, "task_id": task_id}) as resp:
                print("trace status", resp.status)
                tr = await resp.json()
                print("trace items", len(tr["trace"]), tr["trace"][0]["type"])
            # diff
            async with session.post(base + "/api/snapshot/diff", data={"snapshot_id_1": sid, "snapshot_id_2": sid}) as resp:
                print("diff status", resp.status)
                dd = await resp.json()
                print("diff keys", list(dd.keys()), len(dd["common"]))
            # delete
            async with session.delete(base + f"/api/snapshot?snapshot_id={sid}") as resp:
                print("delete status", resp.status, await resp.text())
            # missing
            async with session.post(base + "/api/snapshot/tasks", data={"snapshot_id": 999}) as resp:
                print("missing tasks status", resp.status)
            async with session.delete(base + "/api/snapshot?snapshot_id=999") as resp:
                print("missing delete status", resp.status)
            # page
            async with session.get(base + "/snapshots") as resp:
                print("page status", resp.status, "Snapshots" in await resp.text())
        t.cancel()
        await asyncio.sleep(0.05)


asyncio.run(main())
EOF
python /tmp/web_test.py