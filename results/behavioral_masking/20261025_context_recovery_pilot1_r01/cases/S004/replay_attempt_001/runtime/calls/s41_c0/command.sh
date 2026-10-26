cd /app && python - <<'EOF'
from pathlib import Path
p = Path('aiomonitor/termui/commands.py')
s = p.read_text()

old = """from .completion import (
    ClickCompleter,
    complete_signal_names,
    complete_task_id,
    complete_trace_id,
)"""
new = """from .completion import (
    ClickCompleter,
    complete_signal_names,
    complete_snapshot_id,
    complete_snapshot_task_id,
    complete_task_id,
    complete_trace_id,
)"""
assert old in s
s = s.replace(old, new)

old = '''def print_fail(msg: str) -> None:
    print_formatted_text(
        FormattedText([
            ("ansibrightred", "✗ "),
            ("", msg),
        ])
    )
'''
new = '''def print_fail(msg: str) -> None:
    print_formatted_text(
        FormattedText([
            ("ansibrightred", "✗ "),
            ("", msg),
        ])
    )


def _print_formatted_stack(
    formatted_stack_list,
    stdout: TextIO,
) -> None:
    for item_type, item_text in formatted_stack_list:
        if item_type == "header":
            stdout.write("\\n")
            print_formatted_text(
                FormattedText([
                    ("ansiwhite", item_text),
                ])
            )
        else:
            stdout.write(textwrap.indent(item_text.strip("\\n"), "  "))
            stdout.write("\\n")
'''
assert old in s
s = s.replace(old, new)

p.write_text(s)
print("ok")
EOF