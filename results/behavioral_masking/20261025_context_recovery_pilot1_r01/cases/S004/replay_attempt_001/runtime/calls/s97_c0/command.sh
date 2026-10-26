cd /app && python - <<'EOF'
from aiomonitor.termui.commands import monitor_cli
# list commands
print(sorted(monitor_cli.list_commands(None)))
# snapshot subcommands
snap = monitor_cli.get_command(None, "snapshot")
print(sorted(snap.list_commands(None)))
EOF