python - <<'EOF'
import inspect
import click.shell_completion as sc
print(inspect.getsource(sc._resolve_incomplete))
print(inspect.getsource(sc._resolve_context))
print(inspect.getsource(sc.split_arg_string))
EOF