cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/commands.py')
s = p.read_text()

old = "from typing import TYPE_CHECKING, List, TextIO, Tuple"
new = "from typing import TYPE_CHECKING, List, Sequence, TextIO, Tuple"
assert old in s
s = s.replace(old, new)

old = '''def _print_snapshot_tasks_table(
    stdout: TextIO,
    title: str,
    headers: Tuple[str, ...],
    rows: List[Tuple[str, ...]],
) -> None:
    stdout.write(f"\\n{title}\\n")
    table_data = [headers, *rows]
'''
new = '''def _print_snapshot_tasks_table(
    stdout: TextIO,
    title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    stdout.write(f"\\n{title}\\n")
    table_data = [list(headers), *[list(row) for row in rows]]
'''
assert old in s
s = s.replace(old, new)

old = """    def rows_of(items) -> List[Tuple[str, ...]]:
        rows = []
        for item in items:
            rows.append((
                item.task_id,
                item.kind,
                item.info.name,
                item.info.coro,
            ))
        return rows
"""
new = """    def rows_of(items) -> List[Tuple[str, ...]]:
        rows: List[Tuple[str, ...]] = []
        for item in items:
            rows.append((
                item.task_id,
                item.kind,
                item.info.name,
                item.info.coro,
            ))
        return rows
"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
ruff check aiomonitor tests 2>&1 | tail -10
mypy aiomonitor 2>&1 | tail -20