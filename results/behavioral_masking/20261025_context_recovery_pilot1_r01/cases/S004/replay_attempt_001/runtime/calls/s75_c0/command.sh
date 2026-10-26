cd /app && cat >> tests/test_monitor.py <<'EOF'


@pytest.mark.asyncio
async def test_snapshot_timing_fields_with_hook() -> None:
    loop = asyncio.get_running_loop()

    async def sleeper() -> None:
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="hooked")
        await asyncio.sleep(0.01)
        snapshot_id = await mon.capture_snapshot()
        tasks = mon.format_snapshot_task_list(snapshot_id)
        hooked = [task for task in tasks if task.name == "hooked"][0]
        assert hooked.since != "-"
        assert hooked.created_location != "-"
        root = [task for task in tasks if task.created_location == "-"][0]
        assert root.since == "-"
        t.cancel()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_snapshot_web_api() -> None:
    import aiohttp.test_utils

    from aiomonitor.webui.app import init_webui

    loop = asyncio.get_running_loop()

    async def sleeper() -> None:
        await asyncio.sleep(100)

    with Monitor(loop, console_enabled=False, hook_task_factory=True) as mon:
        t = loop.create_task(sleeper(), name="web-sleeper")
        await asyncio.sleep(0.01)
        app = await init_webui(mon)
        client = aiohttp.test_utils.TestClient(
            aiohttp.test_utils.TestServer(app)
        )
        async with client:
            resp = await client.post("/api/snapshot/", data={"name": "web"})
            assert resp.status == 200
            snapshot_id = (await resp.json())["id"]

            resp = await client.get("/api/snapshot/")
            assert resp.status == 200
            snapshots = (await resp.json())["snapshots"]
            assert any(s["id"] == snapshot_id for s in snapshots)

            resp = await client.post(
                "/api/snapshot/tasks",
                data={"snapshot_id": snapshot_id},
            )
            assert resp.status == 200
            tasks = (await resp.json())["tasks"]
            assert any(t["name"] == "web-sleeper" for t in tasks)
            task_id = next(
                t["task_id"] for t in tasks if t["name"] == "web-sleeper"
            )

            resp = await client.post(
                "/api/snapshot/trace",
                data={"snapshot_id": snapshot_id, "task_id": task_id},
            )
            assert resp.status == 200
            assert len((await resp.json())["trace"]) > 0

            resp = await client.post(
                "/api/snapshot/diff",
                data={
                    "snapshot_id_1": snapshot_id,
                    "snapshot_id_2": snapshot_id,
                },
            )
            assert resp.status == 200
            diff = await resp.json()
            assert set(diff) == {"added", "removed", "common"}

            resp = await client.delete(
                f"/api/snapshot?snapshot_id={snapshot_id}"
            )
            assert resp.status == 200

            resp = await client.post(
                "/api/snapshot/tasks",
                data={"snapshot_id": 999},
            )
            assert resp.status == 404

            resp = await client.delete("/api/snapshot?snapshot_id=999")
            assert resp.status == 404

            resp = await client.get("/snapshots")
            assert resp.status == 200
            assert "Snapshots" in await resp.text()

        t.cancel()
        await asyncio.sleep(0.05)
EOF
python -m pytest tests/test_monitor.py -q 2>&1 | tail -15