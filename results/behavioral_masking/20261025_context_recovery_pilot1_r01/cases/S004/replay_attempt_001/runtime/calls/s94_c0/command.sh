cd /app && python - <<'EOF'
from pathlib import Path
p = Path('docs/reference/monitor.rst')
s = p.read_text()
old = """   .. autoproperty:: host

   .. autoproperty:: port"""
new = """   .. autoproperty:: host

   .. autoproperty:: port

   .. automethod:: capture_snapshot

   .. automethod:: list_snapshots

   .. automethod:: get_snapshot

   .. automethod:: delete_snapshot

   .. automethod:: format_snapshot_task_list

   .. automethod:: format_snapshot_terminated_task_list

   .. automethod:: format_snapshot_task_stack

   .. automethod:: format_snapshot_diff"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
echo done