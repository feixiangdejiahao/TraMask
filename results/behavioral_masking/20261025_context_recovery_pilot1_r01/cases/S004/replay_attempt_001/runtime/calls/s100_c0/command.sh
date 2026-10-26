cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/webui/app.py')
s = p.read_text()
s = s.replace(
    "from typing import TYPE_CHECKING, Dict, Mapping, Tuple",
    "from typing import TYPE_CHECKING, Any, Dict, Mapping, Tuple",
)
s = s.replace("def _serialize_running_task_info(t) -> Dict[str, str]:", "def _serialize_running_task_info(t) -> Dict[str, Any]:")
s = s.replace("def _serialize_terminated_task_info(t) -> Dict[str, str]:", "def _serialize_terminated_task_info(t) -> Dict[str, Any]:")
s = s.replace("def _serialize_snapshot_task_item(item) -> Dict[str, str]:", "def _serialize_snapshot_task_item(item) -> Dict[str, Any]:")
p.write_text(s)
print("ok")
EOF
ruff check aiomonitor/webui/app.py && mypy aiomonitor/webui/app.py && echo OK