cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/webui/app.py')
s = p.read_text()

old = """class ListFilterParams(APIParams):
    filter: str = Field(default=\"\")
    persistent: bool = Field(default=False)
"""
new = """class ListFilterParams(APIParams):
    filter: str = Field(default=\"\")
    persistent: bool = Field(default=False)


class SnapshotIdParams(APIParams):
    snapshot_id: str


class SnapshotSaveParams(APIParams):
    name: str = Field(default=\"\")


class SnapshotTaskParams(APIParams):
    snapshot_id: str
    task_id: str


class SnapshotDiffParams(APIParams):
    snapshot_id_1: str
    snapshot_id_2: str
"""
assert old in s
s = s.replace(old, new)

old = """nav_menus: Mapping[str, NavigationItem] = {
    \"/\": NavigationItem(
        title=\"Dashboard\",
        current=False,
    ),
    \"/about\": NavigationItem(
        title=\"About\",
        current=False,
    ),
}
"""
new = """nav_menus: Mapping[str, NavigationItem] = {
    \"/\": NavigationItem(
        title=\"Dashboard\",
        current=False,
    ),
    \"/snapshots\": NavigationItem(
        title=\"Snapshots\",
        current=False,
    ),
    \"/about\": NavigationItem(
        title=\"About\",
        current=False,
    ),
}
"""
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF