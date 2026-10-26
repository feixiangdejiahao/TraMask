cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/webui/app.py')
s = p.read_text()

anchor = """async def init_webui(monitor: Monitor) -> web.Application:
"""
insert = '''def _serialize_running_task_info(t) -> Dict[str, str]:
    return {
        "task_id": t.task_id,
        "state": t.state,
        "name": t.name,
        "coro": t.coro,
        "created_location": t.created_location,
        "since": t.since,
        "is_root": t.created_location == "-",
    }


def _serialize_terminated_task_info(t) -> Dict[str, str]:
    return {
        "task_id": t.task_id,
        "name": t.name,
        "coro": t.coro,
        "started_since": t.started_since,
        "terminated_since": t.terminated_since,
    }


def _serialize_snapshot_task_item(item) -> Dict[str, str]:
    if item.kind == "running":
        data = _serialize_running_task_info(item.info)
        data.pop("is_root", None)
        data["kind"] = item.kind
        data["task_id"] = item.task_id
        return data
    data = _serialize_terminated_task_info(item.info)
    data["kind"] = item.kind
    data["task_id"] = item.task_id
    return data


async def show_snapshots_page(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    nav_info, nav_items = get_navigation_info(request.path)
    template = ctx.jenv.get_template("snapshots.html")
    output = template.render(
        navigation=nav_items,
        page={
            "title": nav_info.title,
        },
    )
    return web.Response(body=output, content_type="text/html")


async def save_snapshot(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    async with check_params(request, SnapshotSaveParams) as params:
        name = params.name or None
        snapshot_id = await ctx.monitor.capture_snapshot(name=name)
        return web.json_response(
            data={
                "id": snapshot_id,
            }
        )


async def list_snapshots(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    snapshots = ctx.monitor.list_snapshots()
    return web.json_response(
        data={
            "snapshots": [
                {
                    "id": s.id,
                    "name": s.name,
                    "running_count": s.running_count,
                    "terminated_count": s.terminated_count,
                }
                for s in snapshots
            ]
        }
    )


async def get_snapshot_tasks(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    async with check_params(request, SnapshotIdParams) as params:
        try:
            tasks = ctx.monitor.format_snapshot_task_list(params.snapshot_id)
        except KeyError:
            raise web.HTTPNotFound(
                content_type="application/json",
                body='{"msg": "No snapshot %s"}' % params.snapshot_id,
            ) from None
        return web.json_response(
            data={
                "tasks": [_serialize_running_task_info(t) for t in tasks],
            }
        )


async def get_snapshot_trace(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    async with check_params(request, SnapshotTaskParams) as params:
        try:
            trace_data = ctx.monitor.format_snapshot_task_stack(
                params.snapshot_id,
                params.task_id,
            )
        except KeyError:
            raise web.HTTPNotFound(
                content_type="application/json",
                body='{"msg": "No snapshot or task"}',
            ) from None
        return web.json_response(
            data={
                "trace": [
                    {
                        "type": str(item.type),
                        "content": item.content,
                    }
                    for item in trace_data
                ]
            }
        )


async def get_snapshot_diff(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    async with check_params(request, SnapshotDiffParams) as params:
        try:
            diff = ctx.monitor.format_snapshot_diff(
                params.snapshot_id_1,
                params.snapshot_id_2,
            )
        except KeyError:
            raise web.HTTPNotFound(
                content_type="application/json",
                body='{"msg": "No snapshot"}',
            ) from None
        return web.json_response(
            data={
                "added": [
                    _serialize_snapshot_task_item(item) for item in diff.added
                ],
                "removed": [
                    _serialize_snapshot_task_item(item) for item in diff.removed
                ],
                "common": [
                    _serialize_snapshot_task_item(item) for item in diff.common
                ],
            }
        )


async def delete_snapshot(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    async with check_params(request, SnapshotIdParams) as params:
        try:
            ctx.monitor.delete_snapshot(params.snapshot_id)
        except KeyError:
            raise web.HTTPNotFound(
                content_type="application/json",
                body='{"msg": "No snapshot %s"}' % params.snapshot_id,
            ) from None
        return web.json_response(
            data={
                "msg": f"Deleted snapshot {params.snapshot_id}",
            }
        )


async def init_webui(monitor: Monitor) -> web.Application:
'''
assert anchor in s
s = s.replace(anchor, insert)

old = """    app.router.add_route("GET", "/", show_list_page)
    app.router.add_route("GET", "/about", show_about_page)
    app.router.add_route("GET", "/trace-running", show_trace_page)
    app.router.add_route("GET", "/trace-terminated", show_trace_page)
    app.router.add_route("GET", "/api/version", get_version)
    app.router.add_route("POST", "/api/task-count", get_task_count)
    app.router.add_route("POST", "/api/live-tasks", get_live_task_list)
    app.router.add_route("POST", "/api/terminated-tasks", get_terminated_task_list)
    app.router.add_route("DELETE", "/api/task", cancel_task)"""
new = """    app.router.add_route("GET", "/", show_list_page)
    app.router.add_route("GET", "/snapshots", show_snapshots_page)
    app.router.add_route("GET", "/about", show_about_page)
    app.router.add_route("GET", "/trace-running", show_trace_page)
    app.router.add_route("GET", "/trace-terminated", show_trace_page)
    app.router.add_route("GET", "/api/version", get_version)
    app.router.add_route("POST", "/api/task-count", get_task_count)
    app.router.add_route("POST", "/api/live-tasks", get_live_task_list)
    app.router.add_route("POST", "/api/terminated-tasks", get_terminated_task_list)
    app.router.add_route("DELETE", "/api/task", cancel_task)
    app.router.add_route("POST", "/api/snapshot/", save_snapshot)
    app.router.add_route("GET", "/api/snapshot/", list_snapshots)
    app.router.add_route("POST", "/api/snapshot/tasks", get_snapshot_tasks)
    app.router.add_route("POST", "/api/snapshot/trace", get_snapshot_trace)
    app.router.add_route("POST", "/api/snapshot/diff", get_snapshot_diff)
    app.router.add_route("DELETE", "/api/snapshot", delete_snapshot)"""
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/webui/app.py && echo OK