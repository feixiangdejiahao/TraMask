cd /app && python - <<'EOF'
from pathlib import Path
p = Path('/tmp/cli_test.py')
s = p.read_text()
s = s.replace("""from aiomonitor.termui.commands import (
    command_done,
    current_monitor,
    current_stdout,
    monitor_cli,
)""", """from prompt_toolkit.output import DummyOutput
from aiomonitor.termui.commands import (
    command_done,
    current_monitor,
    current_stdout,
    monitor_cli,
)""")
s = s.replace("class BufferedOutput:", "class BufferedOutput(DummyOutput):")
p.write_text(s)
print("ok")
EOF
python /tmp/cli_test.py