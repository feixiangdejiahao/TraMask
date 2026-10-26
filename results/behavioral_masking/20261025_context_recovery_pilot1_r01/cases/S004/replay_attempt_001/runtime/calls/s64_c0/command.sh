python - <<'EOF'
import inspect, click.shell_completion as sc
print(inspect.getsource(sc._is_incomplete_argument))
EOF