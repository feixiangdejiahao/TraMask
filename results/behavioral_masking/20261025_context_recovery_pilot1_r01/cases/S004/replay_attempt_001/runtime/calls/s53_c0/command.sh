cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/webui/app.py')
s = p.read_text()

old = """async def get_snapshot_tasks(request: web.Request) -> web.Response:
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
"""
new = """async def get_snapshot_tasks(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    try:
        async with check_params(request, SnapshotIdParams) as params:
            tasks = ctx.monitor.format_snapshot_task_list(params.snapshot_id)
            return web.json_response(
                data={
                    "tasks": [_serialize_running_task_info(t) for t in tasks],
                }
            )
    except KeyError:
        raise web.HTTPNotFound(
            content_type="application/json",
            body=json.dumps({"msg": "No snapshot"}),
        ) from None
"""
assert old in s
s = s.replace(old, new)

old = """async def get_snapshot_trace(request: web.Request) -> web.Response:
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
"""
new = """async def get_snapshot_trace(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    try:
        async with check_params(request, SnapshotTaskParams) as params:
            trace_data = ctx.monitor.format_snapshot_task_stack(
                params.snapshot_id,
                params.task_id,
            )
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
    except KeyError:
        raise web.HTTPNotFound(
            content_type="application/json",
            body=json.dumps({"msg": "No snapshot or task"}),
        ) from None
"""
assert old in s
s = s.replace(old, new)

old = """async def get_snapshot_diff(request: web.Request) -> web.Response:
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
"""
new = """async def get_snapshot_diff(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    try:
        async with check_params(request, SnapshotDiffParams) as params:
            diff = ctx.monitor.format_snapshot_diff(
                params.snapshot_id_1,
                params.snapshot_id_2,
            )
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
    except KeyError:
        raise web.HTTPNotFound(
            content_type="application/json",
            body=json.dumps({"msg": "No snapshot"}),
        ) from None
"""
assert old in s
s = s.replace(old, new)

old = """async def delete_snapshot(request: web.Request) -> web.Response:
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
"""
new = """async def delete_snapshot(request: web.Request) -> web.Response:
    ctx: WebUIContext = request.app[ctx_key]
    try:
        async with check_params(request, SnapshotIdParams) as params:
            ctx.monitor.delete_snapshot(params.snapshot_id)
            return web.json_response(
                data={
                    "msg": f"Deleted snapshot {params.snapshot_id}",
                }
            )
    except KeyError:
        raise web.HTTPNotFound(
            content_type="application/json",
            body=json.dumps({"msg": "No snapshot"}),
        ) from None
"""
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF
python -m py_compile aiomonitor/webui/app.py && echo OK