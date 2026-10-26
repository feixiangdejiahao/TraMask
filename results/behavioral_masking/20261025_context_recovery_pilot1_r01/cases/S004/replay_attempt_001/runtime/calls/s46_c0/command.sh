cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/commands.py')
s = p.read_text()
old = """@monitor_cli.group(name="snapshot", aliases=["snap", "sn"])
@custom_help_option
@auto_command_done
def do_snapshot_group(ctx: click.Context) -> None:
    \"\"\"Capture, inspect and compare frozen task state snapshots\"\"\"
"""
new = """@monitor_cli.group(name="snapshot", aliases=["snap", "sn"])
@click.pass_context
@custom_help_option
@auto_command_done
def do_snapshot_group(ctx: click.Context) -> None:
    \"\"\"Capture, inspect and compare frozen task state snapshots\"\"\"
"""
assert old in s
s = s.replace(old, new)
p.write_text(s)
print("ok")
EOF
python /tmp/cli_test.py